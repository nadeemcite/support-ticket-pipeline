"""Reply drafting (SPEC §7.2): one LLM call per ticket, checked against D3-D11, retried with the violations,
then a language-aware template (DF) after three failed attempts.

Checks run on the model output before it is accepted; a draft that breaks any hard rule is never written.
Grounding (G1-G3) runs afterwards and only flags.
"""

from dataclasses import dataclass

from pydantic import ValidationError

from pipeline import guards
from pipeline.language import is_supported, language_code
from pipeline.llm import CallResult, LLMClient, echo_for_retry, parse_json_object
from pipeline.prompts import DRAFT_VERSION, draft_json_schema, draft_messages, draft_retry_feedback
from pipeline.schemas import Classification, DraftMeta, DraftOutput, DraftResponse, KBArticle, NormalisedTicket
from pipeline.taxonomy import LLMStage, PIIType, ResolutionAction

MAX_ATTEMPTS = 3
OUTPUT_ARTIFACT = "draft_responses.json"

# DF templates: no digits, no card/secret words, no refund wording, so they pass S1/S2/V13/V14 by construction.
TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "ack": "Thank you for contacting us. We have received your message and reviewed it.",
        "escalation": "We have escalated your case to our specialist team, who will review it with you.",
        "more_info": "To help you further, please reply with the relevant order number, the date it happened, and any error message or screenshot.",
        "password": "For your security, never share your password or any verification codes with anyone, including us. If you shared them, please change your password now.",
        "followup": "A support specialist will follow up with you.",
    },
    "es": {
        "ack": "Gracias por contactarnos. Hemos recibido y revisado su mensaje.",
        "escalation": "Hemos escalado su caso a nuestro equipo especializado, que lo revisará con usted.",
        "more_info": "Para ayudarle mejor, responda con el número de pedido, la fecha en que ocurrió y cualquier mensaje de error o captura de pantalla.",
        "password": "Por su seguridad, nunca comparta su contraseña ni sus códigos de verificación con nadie, ni siquiera con nosotros. Si los compartió, cambie su contraseña ahora.",
        "followup": "Un especialista de soporte se pondrá en contacto con usted.",
    },
    "fr": {
        "ack": "Merci de nous avoir contactés. Nous avons bien reçu et examiné votre message.",
        "escalation": "Nous avons transmis votre dossier à notre équipe spécialisée, qui l'examinera avec vous.",
        "more_info": "Pour mieux vous aider, répondez avec le numéro de commande, la date concernée et tout message d'erreur ou capture d'écran.",
        "password": "Pour votre sécurité, ne partagez jamais votre mot de passe ni vos codes de vérification avec personne, y compris nous. Si vous les avez partagés, changez votre mot de passe maintenant.",
        "followup": "Un spécialiste du support reviendra vers vous.",
    },
    "de": {
        "ack": "Vielen Dank für Ihre Nachricht. Wir haben sie erhalten und geprüft.",
        "escalation": "Wir haben Ihren Fall an unser Fachteam weitergeleitet, das ihn mit Ihnen prüfen wird.",
        "more_info": "Damit wir Ihnen besser helfen können, antworten Sie bitte mit der Bestellnummer, dem Datum und einer eventuellen Fehlermeldung oder einem Screenshot.",
        "password": "Zu Ihrer Sicherheit: Geben Sie Ihr Passwort und Verifizierungscodes niemals an andere weiter, auch nicht an uns. Falls Sie sie weitergegeben haben, ändern Sie Ihr Passwort bitte jetzt.",
        "followup": "Ein Support-Spezialist wird sich bei Ihnen melden.",
    },
    "pt": {
        "ack": "Obrigado por entrar em contato. Recebemos e analisamos a sua mensagem.",
        "escalation": "Encaminhamos o seu caso para a nossa equipe especializada, que irá analisá-lo com você.",
        "more_info": "Para ajudar melhor, responda com o número do pedido, a data em que ocorreu e qualquer mensagem de erro ou captura de tela.",
        "password": "Para a sua segurança, nunca compartilhe a sua senha nem códigos de verificação com ninguém, nem mesmo conosco. Se os compartilhou, altere a sua senha agora.",
        "followup": "Um especialista de suporte entrará em contato com você.",
    },
}
TEMPLATE_LANGUAGES = tuple(TEMPLATES)


def credential_disclosed(ticket: NormalisedTicket) -> bool:
    """C5 context: the customer pasted a password or code into the ticket."""
    return any(entry.type == PIIType.CREDENTIAL for entry in ticket.pii_summary)


def template_language(language: str) -> str:
    code = language_code(language)
    return code if code in TEMPLATES else "en"


def unsupported_language_draft(ticket: NormalisedTicket) -> DraftResponse:
    """E6: no model call. The safety patterns only cover en/es/fr/de/pt, so an LLM reply in another language could not
    be checked. A short English holding note goes out and the ticket is escalated so a person replies."""
    t = TEMPLATES["en"]
    parts = [t["ack"], t["escalation"]]
    if credential_disclosed(ticket):
        parts.append(t["password"])
    parts.append(t["followup"])
    return DraftResponse(
        ticket_id=ticket.ticket_id, draft_response=" ".join(parts), citations=[],
        meta=DraftMeta(language="en", fallback=True, attempts=0, violations_resolved=[]),
    )


def fallback_draft(ticket: NormalisedTicket, classification: Classification) -> DraftResponse:
    lang = template_language(ticket.language)
    t = TEMPLATES[lang]
    parts = [t["ack"]]
    if classification.resolution_action == ResolutionAction.NEEDS_HUMAN_ESCALATION:
        parts.append(t["escalation"])
    if classification.resolution_action == ResolutionAction.REQUEST_MORE_INFO:
        parts.append(t["more_info"])
    if credential_disclosed(ticket):
        parts.append(t["password"])
    parts.append(t["followup"])
    return DraftResponse(
        ticket_id=ticket.ticket_id, draft_response=" ".join(parts), citations=[],
        meta=DraftMeta(language=lang, fallback=True, attempts=MAX_ATTEMPTS, violations_resolved=[]),
    )


def check_draft(
    output: DraftOutput, ticket: NormalisedTicket, classification: Classification, retrieved_ids: list[str], max_chars: int
) -> list[tuple[str, str]]:
    """Hard-rule violations as (code, message). An empty list means the draft is acceptable."""
    text = output.draft_response
    found: list[tuple[str, str]] = []
    if output.ticket_id != ticket.ticket_id:
        found.append(("ID", f'ticket_id must be "{ticket.ticket_id}"'))
    unknown = [c for c in output.citations if c not in retrieved_ids]
    if unknown:
        found.append(("D3", f"citations {unknown} are not in the evidence provided ({retrieved_ids})"))
    if retrieved_ids and classification.resolution_action == ResolutionAction.ANSWER_FROM_KB and not output.citations:
        found.append(("D4", "cite at least one evidence article ID"))
    if guards.s1_credential_request(text):
        found.append(("D5", "never ask for a password, PIN, code, CVV or full card number"))
    if classification.requires_refund_caution and guards.s2_refund_promise(text):
        found.append(("D6", "do not promise, guarantee or announce a refund; say the billing team will review"))
    if classification.resolution_action == ResolutionAction.NEEDS_HUMAN_ESCALATION and not guards.s3_escalation_mention(text):
        found.append(("D7", "tell the customer the case has been escalated to a specialist team"))
    if not 1 <= len(text) <= max_chars:
        found.append(("D9", f"length must be between 1 and {max_chars} characters"))
    if credential_disclosed(ticket) and not guards.has_credential_advice(text):
        found.append(("D10", "tell the customer to never share their password or codes"))
    if guards.has_pii(text) or guards.has_placeholder(text):
        found.append(("D11", "no personal data and no [TYPE_n] placeholders; refer to data generically"))
    return found


@dataclass(frozen=True)
class DraftAttempt:
    status: str
    output: DraftOutput | None
    violations: list[tuple[str, str]]


def _attempt(result: CallResult, ticket: NormalisedTicket, classification: Classification, retrieved_ids: list[str], max_chars: int) -> DraftAttempt:
    if result.error:
        return DraftAttempt("transport_error", None, [("T", result.error)])
    try:
        data = parse_json_object(result.text)
    except ValueError as exc:
        return DraftAttempt("invalid_json", None, [("JSON", f"not a valid JSON object ({exc})")])
    try:
        output = DraftOutput.model_validate(data)
    except ValidationError as exc:
        return DraftAttempt("schema_error", None, [("SCHEMA", f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}") for err in exc.errors()])
    violations = check_draft(output, ticket, classification, retrieved_ids, max_chars)
    return DraftAttempt("rule_violation" if violations else "ok", None if violations else output, violations)


def draft_ticket(
    client: LLMClient, ticket: NormalisedTicket, classification: Classification, evidence: list[KBArticle],
    input_artifacts: list[str], max_chars: int,
) -> DraftResponse:
    if not is_supported(ticket.language):
        return unsupported_language_draft(ticket)
    retrieved_ids = [a.article_id for a in evidence]
    messages = draft_messages(ticket, classification, evidence, credential_disclosed(ticket), max_chars)
    schema = draft_json_schema()
    seen: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = client.call(LLMStage.DRAFTING, messages, DRAFT_VERSION, schema)
        outcome = _attempt(result, ticket, classification, retrieved_ids, max_chars)
        client.log(
            llm_stage=LLMStage.DRAFTING, ticket_id=ticket.ticket_id, result=result, prompt_version=DRAFT_VERSION,
            input_artifacts=input_artifacts, output_artifact=OUTPUT_ARTIFACT, attempt=attempt, status=outcome.status,
        )
        seen.extend(code for code, _ in outcome.violations if code not in seen)
        if outcome.output is not None:
            return DraftResponse(
                ticket_id=ticket.ticket_id, draft_response=outcome.output.draft_response.strip(), citations=outcome.output.citations,
                meta=DraftMeta(language=ticket.language, fallback=False, attempts=attempt, violations_resolved=seen),
            )
        if outcome.status != "transport_error":
            messages = [*messages, {"role": "assistant", "content": echo_for_retry(result.text)},
                        {"role": "user", "content": draft_retry_feedback([m for _, m in outcome.violations])}]
    draft = fallback_draft(ticket, classification)
    draft.meta.violations_resolved = seen
    return draft
