#!/usr/bin/env python3
"""Queue the May 2026 CRM follow-up wave for Contadores and Abogados."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from backend.database import (
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    MessageDeliveryStatus,
    WorkstationClient,
)
from backend.endpoints.contadores import (
    build_manual_ping_text,
    build_opener_followup_text,
    derive_effective_lead_stage,
    get_effective_funnel_config,
    is_whatsapp_custom_window_open,
    queue_manual_message_for_lead,
    resolve_contadores_template_name,
    run_quick_action_for_lead,
    send_opener_followup,
)


WAVE_ID = "crm_followup_wave_20260502"
DEFAULT_PREVIEW_PATH = Path("data/reports/crm-followup-wave-2026-05-02-preview.csv")
DEFAULT_LEDGER_PATH = Path("data/contadores/crm-followup-wave-2026-05-02-ledger.json")
VENEZUELA_MOBILE_PREFIXES = ("412", "414", "416", "424", "426")
NON_DIGITS_RE = re.compile(r"\D+")

CLOSE_CALL_TEXT = (
    "Hola {name}, le gustaria agendar una reunion corta para conocernos y sacarse "
    "las ultimas dudas? Digame que dia y horario le queda bien y lo coordinamos."
)
ANSWER_MANUAL_TEXT = (
    "Hola {name}, le respondo por aca. Nosotros trabajamos para toda latinoamerica "
    "y la idea es traerle clientes potenciales a su WhatsApp con pagina web y campanas. "
    "Si le sirve, hacemos una reunion corta y resolvemos las ultimas dudas. "
    "Digame que dia y horario le queda bien."
)
RETOMAR_VIDEO_TEXT = (
    "Hola {name}, pudiste ver el video? Queria saber si te interesa avanzar o si "
    "quedo alguna duda de la propuesta."
)

REPAIR_FAILED_MESSAGE_IDS: tuple[int, ...] = (
    1867,
    868,
    2037,
    866,
    1214,
    962,
    859,
    2096,
    1272,
    1642,
    1979,
    557,
    2035,
    1621,
    853,
    290,
    1207,
    303,
    1336,
    1206,
    283,
    310,
    302,
    956,
    547,
    1731,
    316,
    312,
    294,
    280,
    292,
    822,
    273,
    293,
    1666,
    317,
    2077,
    285,
)

ANSWER_MANUAL_LEAD_IDS: tuple[str, ...] = (
    "0055598c-3d32-4d5e-9fd5-15d4a51b2844",
)

CLOSE_CALL_LEAD_IDS: tuple[str, ...] = (
    "d820c4fe-f099-4656-843d-42bc91e807e5",
    "e9305e45-5537-4786-9141-96e2d98b44fd",
    "11dc1010-6c56-44be-810a-be3f9e4d8024",
    "59840ae6-9820-4493-8f03-04c2c93b996c",
    "d9046eda-5c4d-4c33-bb76-594811f12bbc",
    "587fff69-75aa-4c42-9f07-90dd8a12bf58",
    "961ff10d-431a-46f6-a315-a3cfbe82e67d",
    "00251083-586d-4de9-a8f5-4206006dec21",
    "03b20bb2-0fef-48e3-91cc-57b5d0d0b8e7",
    "d7dd0a74-95d9-420a-8562-9048b390080a",
    "96255a8d-a69f-46b8-b2da-b8b26425ba22",
    "b9d073df-9bae-4f61-be0e-88136b590b7f",
    "0738d9ec-0c24-4eef-95a7-45ead223e7c4",
    "19615e79-035e-4a0d-a18e-79f5c86af7b4",
    "5cbdc1e3-9f18-4f46-800c-09f86776c6e9",
    "1442bc2d-3201-436c-84a1-591b229aa8f1",
    "159a0594-d592-4614-a604-370efad2d049",
    "5d28501f-6971-49fe-94b4-9866da71b1d0",
    "67792a13-3c78-4fbd-a5a5-3ef2fa42fedb",
    "361d41a2-df1a-470e-bdb8-86ff4cce2ec1",
    "fb6440bd-22c1-4939-834e-74b5453899ac",
    "cb11109e-1701-46db-a439-32738d4d7a43",
    "449a4556-e5a4-4bf4-8cb5-bd1c37c0dd25",
    "9e8b78b3-191e-413c-9900-df4039fe81c6",
    "45f864e2-90d1-4bc5-ace8-afc66e0aad5d",
    "2bd8bd25-0abb-46a0-817f-9b2fed9a79a0",
    "59af8a6a-daa6-4461-afde-4360d39530e8",
    "411c164a-ddec-4141-949c-d42c4a640de3",
)

RETOMAR_VIDEO_LEAD_IDS: tuple[str, ...] = (
    "4a6dc0ea-693a-4675-903b-f389a5620f70",
    "5366577a-3b1e-4519-a9fd-6736ed7201d0",
    "434fc3aa-68b7-456d-8378-d98beb299ab7",
    "5a984589-3619-483b-ba1b-bf245848ba39",
    "4aca2dce-1b1d-4994-9cee-8cfd6e4f59e3",
    "591e3e83-2347-4d33-9167-0665e32ccc87",
    "c534b405-255d-45b1-8658-c7da627309e7",
    "ca37d032-3e76-48cc-9b03-93faff4e5d1f",
    "90b56be1-17e2-4fa1-b13c-5036089732a1",
    "fa6c52a9-e2f0-49ca-b58f-b803571efe85",
    "848bfa50-5e58-4e60-b097-f354ad356d35",
    "1e7ad3f5-3354-4eb3-aa1e-c9828cd04486",
    "d54fd854-10f0-41fe-9d0b-beff78df8126",
    "4c822f36-8ff6-403b-85d3-71ee9fd17b66",
    "08ddd065-3d5d-43bb-886d-a6a006d48c4b",
    "d129dff7-2b5f-4f9f-a521-90df642d38af",
    "e616c01c-811c-4416-b93f-85096d144e72",
    "97203e27-6a42-41c2-8fa3-9e6c5a7b96ba",
    "6a065095-c7ad-4096-881b-b041d9ab46d1",
    "48f0e808-af23-458b-8e9b-79e117fc52b2",
    "6433fe5d-f0b6-4c6c-9f9e-6989c2e5fd89",
    "d2282505-82dc-443c-920b-5e2db3dd2e07",
    "1225ee9b-f7fe-45da-951a-fbe317597d02",
    "50b00621-2099-44e4-9cc4-05b534ad9a48",
    "285c36f4-c216-4b45-b86b-0e850bf11165",
    "d8e10726-603b-4293-9ad3-32cb74e366d2",
    "9dd76b03-78d4-4d23-9ad8-a3e8759ea1f3",
    "38bb9d73-29d9-45f9-affc-37c09779947c",
    "e5e64b1d-e79b-46d1-84d2-72d6ad888ecd",
    "526df736-2908-4086-bcb4-c48cda4eb111",
    "0c446f38-a511-437a-a954-68d995a50008",
    "b94d1d99-9b08-4a78-ba64-db43eddbc302",
    "c96cbfeb-3368-4692-99d7-708cb0690cfb",
    "939858cd-167d-4ff6-acf4-07a7cbff4eb5",
    "ae0a9d1c-a20a-4eb1-95db-0c51d51089c6",
    "bf0cf677-9e9d-44a5-99d3-c9e6a925c0d3",
    "363ba1be-32bb-474b-a737-7171df376ead",
    "c53f43f9-3e18-4305-9f76-376c9f9943dd",
    "5b9311b8-f2bc-4162-8be1-c625079f7ab6",
    "6505fd15-2203-407d-ae74-39500dbf8a74",
    "1a66d648-a0f7-487a-ab33-302d581fedd8",
    "8559dffb-7277-4dd4-ab67-afd4fad764c5",
    "7c6b750f-67f2-414a-a81f-bba9149a96a8",
    "1b37cb60-502d-4acb-9f4b-f5f324c39983",
    "3b7d54ec-1db0-4024-b44a-649ff77d56ec",
    "50d53e76-ba8a-453e-8e6f-5d65dea9d301",
    "26b83af3-56e4-4c96-a266-d8ffcdff5e12",
    "485512f7-eefb-40bb-90d5-f7dbb9455f8e",
    "22aafd16-4a26-4767-b82c-4f739d9d7e3b",
    "89969005-e1b2-43ff-8476-491a1293e58a",
    "208507a5-cbb9-4490-9297-e2a800a5e90d",
    "f63de208-466b-45c5-b8e3-5d90dae39fc1",
    "df5c7890-2c19-4306-9697-5498850a515b",
    "43f38d65-af07-43eb-b55c-4309faa31963",
    "323150fb-daa4-4ab3-9238-d97a0e289fed",
    "0b538727-2cb4-4054-ab19-ad8f6cdedb90",
    "7a97c3fd-ae9b-443f-aced-58157afe07c6",
    "0d9d5bf4-06aa-4eef-814b-8fc6cf6c3bfd",
    "813d816c-cc94-4198-a854-ff4d6a79c38b",
    "17e7f31e-5d2f-414e-87df-045a234ece04",
    "0cf5f1b8-4de6-44a9-ab32-b4e14261cb02",
    "3dbabd2c-940a-4a59-a56e-b3cf505a8f60",
    "d8e84117-9534-4271-a7a0-c521f3d428fd",
    "8f854143-5552-4190-8859-6e82d0a88175",
    "6d24ea4e-d78f-4d4b-8f97-0de89f111747",
    "bc7b0582-178b-42a7-a172-9e41a98624bc",
    "4128b4fb-1f15-4ac6-8e24-d0515f5a0d57",
    "2bb0237f-a40e-4f1e-a3e4-1dee125ba966",
)

REACTIVATE_FOLLOWUP_LEAD_IDS: tuple[str, ...] = (
    "4ac6afc2-5e19-4ce6-bd63-b1e44b218c69",
    "c276ba6a-7c87-4da6-8457-71d60e16cf96",
    "444dc29d-0864-4ce3-bfb7-415ce1a9ab9b",
    "faed2755-85e7-477b-9be5-9bbf1362554b",
    "5aee093f-0698-4692-9831-7c294478798a",
    "1b8e290b-805c-4b14-94c0-0202cfd087a0",
    "f43523ac-ae10-42f0-b947-bd77676fb922",
    "571584de-18e5-46c8-8bde-a5729e9d3fb8",
    "17fec221-2fa2-4889-bcb6-bc20235afda0",
    "214d2423-5d79-43e5-801b-0f8094fa6699",
    "18e71fcd-a305-4333-bb75-8c13c1121c77",
    "d70a4322-1931-4bee-9461-fb1e2e6acbcf",
    "814dc81f-7020-4670-af2b-22650c652c56",
    "a103825d-c9b1-4b52-a4d5-c0800ea1aa5f",
    "ffcd9241-7b1e-4672-900e-b704fd8e994b",
    "6c07fd01-0ece-4ce2-9fc5-1de06ddc95fe",
    "60164229-b69b-47e1-971c-c6881955e652",
    "2b73bc36-a3e7-4c51-8b0f-9007ece33a09",
)

COLD_MASS_FOLLOWUP_LEAD_IDS: tuple[str, ...] = (
    "3c91cbdd-aeb0-4904-aaef-d15cb10d7351",
    "adbf6187-f22b-4a83-8df3-0c7b4eb3dd2c",
    "270c956e-af6b-4433-a15a-49c0efbad351",
    "e1b83c20-203c-4624-bde8-fa70442efd43",
    "639e9247-5ee3-477c-b832-83b63a69b000",
    "6e8131e3-44c8-4706-becb-55f5e3d4a7ec",
    "51f5fa3f-d5bc-431c-a70f-2a8c8ba01126",
    "b7711122-ac37-4b84-bd57-fdcfe26b136a",
    "c2b5d549-d48a-4ce1-8634-993333c1a6b7",
    "caf70156-28f4-4b8d-b6a6-cd2fd37eee6f",
    "60d53d00-fc24-4642-bbe1-d16b61bc189a",
    "017b6353-9b10-4466-9136-a97199682190",
    "f8b87809-140c-4dac-8459-886a5d693146",
    "318484f2-4251-4307-8c77-280a2d2ef298",
    "02c52bad-af92-44a9-a67b-2494c4e1ef47",
    "675b2f86-e8bb-49d0-ac33-1cf2090ae22f",
    "fa64ef2c-d256-4de1-bf3c-ebd8ab967444",
    "7897e1ca-d0c9-465f-b46e-1367d2e7c932",
    "6ea87aa6-33fc-41a9-9cee-2b50da511a2d",
    "a73a2130-3e9b-4986-939d-051b84f7182e",
    "40003c35-1c74-4dab-9ee5-0b40062fab11",
    "63d88455-0ead-4fa6-b0b5-22fe3f3914da",
    "7131844d-e2dd-4cba-a197-1975d55e6604",
    "e3b1b3f3-0477-40a3-a091-d504607b27be",
    "c2085af7-7467-45f0-83ed-7573cc00579d",
    "c54ef48c-774c-444c-8d10-7e6663300b93",
    "6a597734-4b07-45de-9ea3-15044e90d528",
    "d063e3db-16f1-41c0-b0a7-da486f75a3ec",
    "4b1ec70a-a996-4515-ba29-93526e19dc9a",
    "a78bbc33-88c9-45f7-8f0f-cb1735bbe41c",
    "fca97f0f-6453-49f7-84a0-23d549e2d439",
    "e74df3a5-ef7c-4375-aaff-65da312d1920",
    "16ae7435-3be4-445d-94bc-c1f4d75f4585",
    "242d6d9a-fe69-4106-b0cb-2efdbeffb09d",
    "fc26434b-2029-4bf5-9f4f-3fa9e9518626",
    "71118d42-f35b-41f0-afd3-3c1ba9922312",
    "bcb6cf35-7e87-4d01-9e1b-4a122fc75c3f",
    "e45163e7-14e7-42ec-9514-439ce05f5033",
    "1f25e7ba-ca8f-4e00-b395-5c51c033fb08",
    "046062a1-843d-4ba2-8f15-0c8433dcd899",
    "a9409aaf-d806-48f4-bf26-f283cbc55fd9",
    "a46ca6df-3931-4620-bc5e-a032adf878c8",
    "de5f2c10-25ff-4e63-bdcb-b045c5a03d68",
    "e34a53a3-efd8-4429-b8d0-d1edc2f27568",
    "a1182781-98ad-488a-ac71-004984a6651b",
    "686bd80d-806f-4a74-ac9f-1b1099910159",
    "3cc80b03-e8ae-44f9-97da-292ec374bbe5",
    "a9e4dad4-8768-4d02-ac86-1f4412204ad1",
    "d3b4a410-aab5-4881-bfed-737e85ea8ad6",
    "d5780c8e-93a0-418a-8396-2d0618d9abc0",
    "342d2fd2-64e9-4a9d-bf64-032c1eb80a9d",
    "61e4040d-7a54-4741-8e8c-ee73f3a8c810",
    "5cebc2bc-4c99-4372-a4cd-70623cbf2c55",
    "337fc8f9-f030-4217-bb7d-6c0b90414cf3",
    "cedd31ed-0a03-4ce1-84d7-0230adf742dc",
    "54cee52e-a1e2-4ec1-b9dd-a915351c8a2e",
    "b3a6b85a-169c-41f6-9d97-e1acdd9a7ec9",
    "41f4b5d4-5f5b-4ce5-aa59-1d411cb1cbc5",
    "35f3b2c2-c7d7-4905-a988-7df294affaae",
    "d0b8d3d5-dc7f-454f-9f44-7bdb1bbce258",
    "b0441bd3-de64-463f-8bb4-06fc1fbc16ef",
    "bf7b9edd-cdd8-4469-8323-00c114642b14",
    "1df578d0-a98c-4fc0-83b0-f0f651744042",
    "5924f3f3-360a-4652-abbd-fd91dbd57231",
    "ef2d32d9-e8f5-4000-9bdf-3ae3fec7a395",
    "95af96fd-c0f6-4a5f-ae24-8d177ec6159a",
    "2138a7d4-065d-48ef-9d79-d263c21454be",
    "cf7130fc-84bd-4c3a-81ea-d8533ab8c604",
    "fe09e4ca-91a4-429f-80a1-f1019fc3dc3f",
    "3f641a56-f885-472c-830f-31273a4ac17c",
    "224e5293-00da-495b-b50f-96df1a4ca7d1",
    "a5e3b6fe-ddb1-4b94-90ea-d2b596884c7a",
    "e3d02c62-0202-4759-b3a1-3842dcb7bdd7",
    "aa7d2768-52db-4228-9f3a-852799176bdd",
    "102ff76b-4e11-43d4-9b83-3482daf657d7",
    "2af973b3-f340-4688-8e6f-ccd5632dcf94",
    "a668e769-14d2-44bd-90e9-3e27d82f3e41",
    "6885b1bb-e109-4d60-8783-ce75570d32a0",
)


@dataclass(frozen=True)
class WaveTarget:
    """One intended outbound action in this follow-up wave."""

    bucket: str
    mode: str
    lead_id: str | None = None
    message_id: int | None = None


@dataclass(frozen=True)
class PlannedSend:
    """Resolved send plan after checking current lead state."""

    bucket: str
    mode: str
    lead_id: str
    message_id: int | None
    funnel_id: str
    lead_name: str
    sequence_step: str
    template_name: str | None
    text: str
    ok: bool
    reason: str


def build_targets(scope: str) -> list[WaveTarget]:
    """Return the static wave target list for the requested scope."""
    targets = [
        *[
            WaveTarget(bucket="repair_delivery", mode="requeue_failed", message_id=message_id)
            for message_id in REPAIR_FAILED_MESSAGE_IDS
        ],
        *[
            WaveTarget(bucket="answer_manual", mode="answer_manual", lead_id=lead_id)
            for lead_id in ANSWER_MANUAL_LEAD_IDS
        ],
        *[
            WaveTarget(bucket="close_call", mode="close_call", lead_id=lead_id)
            for lead_id in CLOSE_CALL_LEAD_IDS
        ],
    ]
    if scope in {"warm", "contactable"}:
        targets.extend(
            WaveTarget(bucket="retomar_video", mode="retomar_video", lead_id=lead_id)
            for lead_id in RETOMAR_VIDEO_LEAD_IDS
        )
    if scope == "contactable":
        targets.extend(
            WaveTarget(bucket="reactivate_followup", mode="opener_followup", lead_id=lead_id)
            for lead_id in REACTIVATE_FOLLOWUP_LEAD_IDS
        )
        targets.extend(
            WaveTarget(bucket="cold_mass_followup", mode="opener_followup", lead_id=lead_id)
            for lead_id in COLD_MASS_FOLLOWUP_LEAD_IDS
        )
    return targets


def first_name(raw_name: str | None) -> str:
    """Return a light personalization token for WhatsApp copy."""
    clean = " ".join((raw_name or "").split()).strip()
    if not clean or clean.startswith("("):
        return ""
    token = clean.split()[0].strip(" ,")
    if not token or token[0].isdigit():
        return ""
    return token


def format_copy(template: str, lead: ContadoresLead) -> str:
    """Personalize one manual text without requiring a name."""
    name = first_name(lead.full_name)
    return template.format(name=name).replace("Hola ,", "Hola,")


def phone_digits(value: str | None) -> str:
    """Return only digits from a phone-like value."""
    return NON_DIGITS_RE.sub("", value or "")


def is_venezuelan_lead(lead: ContadoresLead) -> bool:
    """Return True for the leads the campaign must never contact."""
    normalized_digits = phone_digits(lead.normalized_phone)
    if normalized_digits.startswith("58"):
        return True

    raw_digits = phone_digits(lead.phone)
    if raw_digits.startswith("58"):
        return True
    if len(raw_digits) == 11 and raw_digits.startswith(("0412", "0414", "0416", "0424", "0426")):
        return True
    if len(raw_digits) == 10 and raw_digits.startswith(VENEZUELA_MOBILE_PREFIXES):
        return True
    return False


def blocked_reason(lead: ContadoresLead) -> str | None:
    """Return why a lead cannot receive this wave."""
    if is_venezuelan_lead(lead):
        return "blocked_venezuela"
    if WorkstationClient.get_by_lead_id(lead.id):
        return "blocked_workstation_client"
    if derive_effective_lead_stage(lead) in {
        ContadoresLeadStage.CLOSED,
        ContadoresLeadStage.BOOKED,
        ContadoresLeadStage.ARCHIVED,
    }:
        return "blocked_closed_booked_or_archived"
    return None


def plan_template(
    *,
    bucket: str,
    mode: str,
    lead: ContadoresLead,
    sequence_step: str,
    text: str,
    reason: str,
    message_id: int | None = None,
) -> PlannedSend:
    """Build a resolved template-backed send plan."""
    return PlannedSend(
        bucket=bucket,
        mode=mode,
        lead_id=lead.id,
        message_id=message_id,
        funnel_id=lead.funnel_id,
        lead_name=lead.full_name or "",
        sequence_step=sequence_step,
        template_name=resolve_contadores_template_name(sequence_step, funnel_id=lead.funnel_id),
        text=text,
        ok=True,
        reason=reason,
    )


def plan_manual_or_ping(
    *,
    bucket: str,
    lead: ContadoresLead,
    manual_text: str,
    manual_reason: str,
) -> PlannedSend:
    """Use custom copy when the 24-hour window is open, otherwise use manual ping."""
    if is_whatsapp_custom_window_open(lead):
        return PlannedSend(
            bucket=bucket,
            mode="manual_custom",
            lead_id=lead.id,
            message_id=None,
            funnel_id=lead.funnel_id,
            lead_name=lead.full_name or "",
            sequence_step="manual",
            template_name=None,
            text=manual_text,
            ok=True,
            reason=manual_reason,
        )
    return plan_template(
        bucket=bucket,
        mode="manual_ping_template",
        lead=lead,
        sequence_step="manual_ping_template",
        text=build_manual_ping_text(lead.funnel_id),
        reason="custom_window_closed_use_template",
    )


def plan_target(target: WaveTarget) -> PlannedSend:
    """Resolve one static target against the current database state."""
    message: ContadoresMessage | None = None
    lead: ContadoresLead | None = None
    if target.message_id is not None:
        message = ContadoresMessage.get_by_id(target.message_id)
        if message is None:
            return missing_plan(target, "message_not_found")
        lead = ContadoresLead.get_by_id(message.lead_id)
    elif target.lead_id is not None:
        lead = ContadoresLead.get_by_id(target.lead_id)

    if lead is None:
        return missing_plan(target, "lead_not_found")

    block = blocked_reason(lead)
    if block:
        return skipped_plan(target, lead, block)

    if target.mode == "requeue_failed":
        if message is None:
            return skipped_plan(target, lead, "message_not_found")
        if not message.from_me:
            return skipped_plan(target, lead, "message_not_outbound")
        if message.delivery_status not in {MessageDeliveryStatus.FAILED, MessageDeliveryStatus.UNDELIVERED}:
            return skipped_plan(target, lead, f"message_already_{message.delivery_status.value}")
        return plan_template(
            bucket=target.bucket,
            mode="requeue_failed",
            lead=lead,
            message_id=message.id,
            sequence_step=message.sequence_step or "",
            text=message.text,
            reason="requeue_failed_outbound",
        )

    if target.mode == "answer_manual":
        return plan_manual_or_ping(
            bucket=target.bucket,
            lead=lead,
            manual_text=format_copy(ANSWER_MANUAL_TEXT, lead),
            manual_reason="answer_manual_inside_window",
        )

    if target.mode == "close_call":
        return plan_manual_or_ping(
            bucket=target.bucket,
            lead=lead,
            manual_text=format_copy(CLOSE_CALL_TEXT, lead),
            manual_reason="close_call_inside_window",
        )

    if target.mode == "retomar_video":
        return plan_manual_or_ping(
            bucket=target.bucket,
            lead=lead,
            manual_text=format_copy(RETOMAR_VIDEO_TEXT, lead),
            manual_reason="retomar_video_inside_window",
        )

    if target.mode == "opener_followup":
        return plan_template(
            bucket=target.bucket,
            mode="opener_followup",
            lead=lead,
            sequence_step="opener_followup_24h",
            text=build_opener_followup_text(lead.funnel_id),
            reason="approved_opener_followup_template",
        )

    return skipped_plan(target, lead, "unknown_mode")


def missing_plan(target: WaveTarget, reason: str) -> PlannedSend:
    """Build a failed plan when no lead can be resolved."""
    return PlannedSend(
        bucket=target.bucket,
        mode=target.mode,
        lead_id=target.lead_id or "",
        message_id=target.message_id,
        funnel_id="",
        lead_name="",
        sequence_step="",
        template_name=None,
        text="",
        ok=False,
        reason=reason,
    )


def skipped_plan(target: WaveTarget, lead: ContadoresLead, reason: str) -> PlannedSend:
    """Build a skipped plan with lead context."""
    return PlannedSend(
        bucket=target.bucket,
        mode=target.mode,
        lead_id=lead.id,
        message_id=target.message_id,
        funnel_id=lead.funnel_id,
        lead_name=lead.full_name or "",
        sequence_step="",
        template_name=None,
        text="",
        ok=False,
        reason=reason,
    )


def execute_plan(plan: PlannedSend) -> list[int]:
    """Queue or requeue one planned outbound action."""
    if not plan.ok:
        return []

    if plan.mode == "requeue_failed":
        if plan.message_id is None:
            raise RuntimeError("repair plan is missing message_id")
        row = ContadoresMessage.requeue_failed_delivery(
            message_id=plan.message_id,
            reset_attempts=True,
        )
        return [row.id] if row and row.id else []

    lead = ContadoresLead.get_by_id(plan.lead_id)
    if lead is None:
        raise RuntimeError("lead disappeared before execution")

    if plan.mode == "manual_custom":
        rows = queue_manual_message_for_lead(lead=lead, text=plan.text)
        return [row.id or 0 for row in rows]

    if plan.mode == "manual_ping_template":
        config = get_effective_funnel_config(lead.funnel_id)
        _, rows = run_quick_action_for_lead(
            lead=lead,
            action="send-manual-ping",
            config=config,
        )
        return [row.id or 0 for row in rows]

    if plan.mode == "opener_followup":
        rows = send_opener_followup(lead=lead)
        return [row.id or 0 for row in rows]

    raise RuntimeError(f"unsupported execution mode: {plan.mode}")


def planned_send_to_row(plan: PlannedSend) -> dict[str, object]:
    """Serialize one planned send for CSV/ledger output."""
    return {
        "bucket": plan.bucket,
        "mode": plan.mode,
        "ok": plan.ok,
        "reason": plan.reason,
        "lead_id": plan.lead_id,
        "message_id": plan.message_id or "",
        "funnel_id": plan.funnel_id,
        "lead_name": plan.lead_name,
        "sequence_step": plan.sequence_step,
        "template_name": plan.template_name or "",
        "text": plan.text,
    }


def write_preview(plans: list[PlannedSend], path: Path) -> None:
    """Write the exact resolved wave plan to a CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "bucket",
        "mode",
        "ok",
        "reason",
        "lead_id",
        "message_id",
        "funnel_id",
        "lead_name",
        "sequence_step",
        "template_name",
        "text",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for plan in plans:
            writer.writerow(planned_send_to_row(plan))


def write_ledger(path: Path, *, plans: list[PlannedSend], queued_message_ids: list[int]) -> None:
    """Persist a one-time ledger so the live wave is not run twice by accident."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "wave_id": WAVE_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "queued_message_ids": queued_message_ids,
        "plans": [planned_send_to_row(plan) for plan in plans],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def print_summary(plans: list[PlannedSend], *, live: bool, preview_path: Path) -> None:
    """Print a short operational summary."""
    eligible = [plan for plan in plans if plan.ok]
    blocked = [plan for plan in plans if not plan.ok]
    by_bucket = Counter(plan.bucket for plan in eligible)
    by_mode = Counter(plan.mode for plan in eligible)
    by_text = Counter((plan.mode, plan.template_name or "", plan.text) for plan in eligible)

    print(f"wave_id={WAVE_ID}")
    print(f"live={live}")
    print(f"preview_path={preview_path}")
    print(f"eligible={len(eligible)}")
    print(f"blocked_or_skipped={len(blocked)}")
    print("by_bucket=" + json.dumps(dict(sorted(by_bucket.items())), ensure_ascii=True))
    print("by_mode=" + json.dumps(dict(sorted(by_mode.items())), ensure_ascii=True))
    print("copies:")
    for (mode, template_name, text), count in by_text.most_common():
        template_label = template_name or "custom"
        print(f"- count={count} mode={mode} template={template_label} text={text}")
    if blocked:
        print("blocked:")
        for reason, count in sorted(Counter(plan.reason for plan in blocked).items()):
            print(f"- {reason}: {count}")


def run(*, scope: str, live: bool, force: bool, preview_path: Path, ledger_path: Path) -> int:
    """Resolve and optionally execute the follow-up wave."""
    if live and ledger_path.exists() and not force:
        raise SystemExit(f"ledger exists at {ledger_path}; pass --force to override")

    targets = build_targets(scope)
    plans = [plan_target(target) for target in targets]
    write_preview(plans, preview_path)
    print_summary(plans, live=live, preview_path=preview_path)

    if not live:
        return 0

    queued_message_ids: list[int] = []
    live_failures: list[dict[str, object]] = []
    for plan in plans:
        if not plan.ok:
            continue
        try:
            queued_message_ids.extend(execute_plan(plan))
        except (HTTPException, RuntimeError, ValueError) as exc:
            live_failures.append({**planned_send_to_row(plan), "error": str(exc)})

    write_ledger(ledger_path, plans=plans, queued_message_ids=queued_message_ids)
    print(f"queued_message_ids={len(queued_message_ids)}")
    print(f"live_failures={len(live_failures)}")
    if live_failures:
        print(json.dumps(live_failures, indent=2, ensure_ascii=True))
        return 1
    return 0


def main() -> None:
    """Run the wave planner or live queue."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope",
        choices=("priority", "warm", "contactable"),
        default="contactable",
        help="priority=A1-A3, warm=A1-A4, contactable=A1-A6",
    )
    parser.add_argument("--live", action="store_true", help="Actually queue messages. Default is dry-run.")
    parser.add_argument("--force", action="store_true", help="Allow live run when the ledger already exists.")
    parser.add_argument("--preview-path", type=Path, default=DEFAULT_PREVIEW_PATH)
    parser.add_argument("--ledger-path", type=Path, default=DEFAULT_LEDGER_PATH)
    args = parser.parse_args()

    raise SystemExit(
        run(
            scope=args.scope,
            live=args.live,
            force=args.force,
            preview_path=args.preview_path,
            ledger_path=args.ledger_path,
        )
    )


if __name__ == "__main__":
    main()
