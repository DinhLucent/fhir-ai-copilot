"""
fhir-ai-copilot — Python CLI copilot for FHIR R4 resources:
smart validation, resource templates, HL7 v2.x to FHIR conversion,
and natural language query helpers.

Author: DinhLucent
License: MIT

No external dependencies beyond the Python standard library.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FHIR R4 resource type registry (subset)
# ---------------------------------------------------------------------------

FHIR_RESOURCE_TYPES = {
    "Patient", "Practitioner", "Organization", "Encounter",
    "Condition", "Observation", "MedicationRequest", "DiagnosticReport",
    "Procedure", "Immunization", "AllergyIntolerance", "CarePlan",
    "ServiceRequest", "Appointment", "Location", "Device",
    "Coverage", "Claim", "ExplanationOfBenefit", "Bundle",
}

# Required fields per resource type (FHIR R4 minimum)
REQUIRED_FIELDS: Dict[str, List[str]] = {
    "Patient":           [],             # resourceType & id are implicit
    "Practitioner":      [],
    "Organization":      [],
    "Encounter":         ["status", "class"],
    "Condition":         ["clinicalStatus", "subject"],
    "Observation":       ["status", "code"],
    "MedicationRequest": ["status", "intent", "medication", "subject"],
    "DiagnosticReport":  ["status", "code"],
    "Procedure":         ["status", "subject"],
    "Immunization":      ["status", "vaccineCode", "patient", "occurrenceDateTime"],
    "AllergyIntolerance":["patient"],
    "Bundle":            ["type"],
}

# Valid status values per resource type
VALID_STATUSES: Dict[str, List[str]] = {
    "Encounter":         ["planned", "arrived", "triaged", "in-progress",
                          "onleave", "finished", "cancelled", "unknown"],
    "Condition":         ["active", "recurrence", "relapse", "inactive",
                          "remission", "resolved"],
    "Observation":       ["registered", "preliminary", "final", "amended",
                          "corrected", "cancelled", "entered-in-error", "unknown"],
    "MedicationRequest": ["active", "on-hold", "cancelled", "completed",
                          "entered-in-error", "stopped", "draft", "unknown"],
    "DiagnosticReport":  ["registered", "partial", "preliminary", "final",
                          "amended", "corrected", "appended", "cancelled",
                          "entered-in-error", "unknown"],
    "Procedure":         ["preparation", "in-progress", "not-done", "on-hold",
                          "stopped", "completed", "entered-in-error", "unknown"],
    "Immunization":      ["completed", "entered-in-error", "not-done"],
}

# HL7 v2.x OBX-2 observation types to FHIR Observation value types
HL7_OBX_TYPE_MAP = {
    "NM": "valueQuantity",
    "ST": "valueString",
    "DT": "valueDateTime",
    "TM": "valueTime",
    "TX": "valueString",
    "SN": "valueQuantity",
    "IS": "valueCodeableConcept",
    "CE": "valueCodeableConcept",
    "CWE": "valueCodeableConcept",
    "TS": "valueDateTime",
}

LOINC_COMMON = {
    "8310-5": "Body temperature",
    "8867-4": "Heart rate",
    "9279-1": "Respiratory rate",
    "55284-4": "Blood pressure",
    "29463-7": "Body weight",
    "8302-2": "Body height",
    "2708-6": "Oxygen saturation",
    "2339-0": "Glucose",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class Severity(Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class FHIRIssue:
    path: str
    severity: Severity
    code: str
    message: str
    suggestion: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "path": self.path,
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "suggestion": self.suggestion,
        }

    def __str__(self) -> str:
        icon = {"ERROR": "❌", "WARNING": "⚠️ ", "INFO": "ℹ️ "}[self.severity.value]
        line = f"  {icon} [{self.severity.value}] {self.path}: {self.message}"
        if self.suggestion:
            line += f"\n     💡 {self.suggestion}"
        return line


@dataclass
class ValidationReport:
    resource_type: str
    resource_id: str
    issues: List[FHIRIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[FHIRIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> List[FHIRIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        status = "✅ VALID" if self.is_valid else "❌ INVALID"
        return (
            f"{status} — {self.resource_type}/{self.resource_id} — "
            f"{len(self.errors)} errors, {len(self.warnings)} warnings"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.is_valid,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
        }


class FHIRValidator:
    """Validate FHIR R4 resource dictionaries (JSON-parsed)."""

    def validate(self, resource: Dict[str, Any]) -> ValidationReport:
        resource_type = resource.get("resourceType", "")
        resource_id = str(resource.get("id", ""))
        report = ValidationReport(resource_type=resource_type, resource_id=resource_id)
        issues = report.issues

        # resourceType must be present and known
        if not resource_type:
            issues.append(FHIRIssue(
                path="resourceType",
                severity=Severity.ERROR,
                code="MISSING_RESOURCE_TYPE",
                message="'resourceType' field is required",
                suggestion="Add 'resourceType' key with a valid FHIR resource type",
            ))
            return report

        if resource_type not in FHIR_RESOURCE_TYPES:
            issues.append(FHIRIssue(
                path="resourceType",
                severity=Severity.ERROR,
                code="UNKNOWN_RESOURCE_TYPE",
                message=f"'{resource_type}' is not a known FHIR R4 resource type",
                suggestion=f"Valid types include: {', '.join(sorted(FHIR_RESOURCE_TYPES)[:8])}...",
            ))
            return report

        # id should be present
        if not resource_id:
            issues.append(FHIRIssue(
                path="id",
                severity=Severity.WARNING,
                code="MISSING_ID",
                message="Resource 'id' is strongly recommended",
                suggestion="Use a UUID: e.g. " + str(uuid.uuid4()),
            ))

        # id format validation (URL-safe characters)
        if resource_id and not re.match(r'^[A-Za-z0-9\-.]{1,64}$', resource_id):
            issues.append(FHIRIssue(
                path="id",
                severity=Severity.ERROR,
                code="INVALID_ID_FORMAT",
                message=f"id '{resource_id}' must match [A-Za-z0-9\\-.] and be 1-64 chars",
                suggestion="Use a UUID or alphanumeric identifier",
            ))

        # Required fields per resource type
        required = REQUIRED_FIELDS.get(resource_type, [])
        for req_field in required:
            if req_field not in resource:
                issues.append(FHIRIssue(
                    path=req_field,
                    severity=Severity.ERROR,
                    code="MISSING_REQUIRED_FIELD",
                    message=f"Required field '{req_field}' missing for {resource_type}",
                    suggestion=f"Add '{req_field}' to your {resource_type} resource",
                ))

        # Status validation
        status_val = resource.get("status")
        valid_statuses = VALID_STATUSES.get(resource_type, [])
        if valid_statuses and status_val is not None:
            if str(status_val) not in valid_statuses:
                issues.append(FHIRIssue(
                    path="status",
                    severity=Severity.ERROR,
                    code="INVALID_STATUS",
                    message=f"Status '{status_val}' is invalid for {resource_type}",
                    suggestion=f"Valid values: {', '.join(valid_statuses)}",
                ))

        # meta.profile check
        meta = resource.get("meta", {})
        if not isinstance(meta, dict):
            issues.append(FHIRIssue(
                path="meta",
                severity=Severity.ERROR,
                code="INVALID_META",
                message="'meta' must be an object",
            ))
        elif not meta.get("profile"):
            issues.append(FHIRIssue(
                path="meta.profile",
                severity=Severity.INFO,
                code="MISSING_PROFILE",
                message="No profile declared in meta.profile",
                suggestion="Consider adding a US Core or other IG profile URL",
            ))

        # Resource-specific validations
        self._validate_resource_specific(resource_type, resource, issues)

        return report

    def _validate_resource_specific(
        self,
        rtype: str,
        resource: Dict[str, Any],
        issues: List[FHIRIssue],
    ) -> None:

        if rtype == "Patient":
            self._validate_patient(resource, issues)
        elif rtype == "Observation":
            self._validate_observation(resource, issues)
        elif rtype == "Encounter":
            self._validate_encounter(resource, issues)

    @staticmethod
    def _validate_patient(resource: Dict[str, Any], issues: List[FHIRIssue]) -> None:
        # birthDate format
        bd = resource.get("birthDate")
        if bd is not None:
            if not re.match(r'^\d{4}(-\d{2}(-\d{2})?)?$', str(bd)):
                issues.append(FHIRIssue(
                    path="birthDate",
                    severity=Severity.ERROR,
                    code="INVALID_DATE_FORMAT",
                    message=f"birthDate '{bd}' must be YYYY, YYYY-MM, or YYYY-MM-DD",
                    suggestion="Use ISO 8601 date format: e.g. '1990-05-15'",
                ))

        # gender
        gender = resource.get("gender")
        valid_genders = {"male", "female", "other", "unknown"}
        if gender is not None and str(gender).lower() not in valid_genders:
            issues.append(FHIRIssue(
                path="gender",
                severity=Severity.ERROR,
                code="INVALID_GENDER",
                message=f"gender '{gender}' is invalid",
                suggestion="Valid values: male, female, other, unknown",
            ))

        # name present
        if not resource.get("name"):
            issues.append(FHIRIssue(
                path="name",
                severity=Severity.WARNING,
                code="MISSING_PATIENT_NAME",
                message="Patient name is recommended",
                suggestion="Add a HumanName with 'family' and 'given' arrays",
            ))

    @staticmethod
    def _validate_observation(resource: Dict[str, Any], issues: List[FHIRIssue]) -> None:
        # code should have coding
        code = resource.get("code", {})
        if not isinstance(code, dict) or not code.get("coding"):
            issues.append(FHIRIssue(
                path="code.coding",
                severity=Severity.WARNING,
                code="MISSING_CODING",
                message="Observation.code should include coded values",
                suggestion="Add LOINC coding: {'system': 'http://loinc.org', 'code': '8310-5'}",
            ))

    @staticmethod
    def _validate_encounter(resource: Dict[str, Any], issues: List[FHIRIssue]) -> None:
        enc_class = resource.get("class")
        if enc_class is not None and not isinstance(enc_class, dict):
            issues.append(FHIRIssue(
                path="class",
                severity=Severity.ERROR,
                code="INVALID_CLASS",
                message="Encounter.class must be a Coding object",
                suggestion="Use {'system': 'http://terminology.hl7.org/CodeSystem/v3-ActCode', 'code': 'AMB'}",
            ))


# ---------------------------------------------------------------------------
# Resource Templates
# ---------------------------------------------------------------------------

class FHIRTemplates:
    """Generate ready-to-use FHIR R4 resource templates."""

    @staticmethod
    def patient(
        patient_id: Optional[str] = None,
        family: str = "Doe",
        given: str = "John",
        gender: str = "unknown",
        birth_date: str = "",
    ) -> Dict[str, Any]:
        resource_id = patient_id or str(uuid.uuid4())
        r: Dict[str, Any] = {
            "resourceType": "Patient",
            "id": resource_id,
            "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]},
            "name": [{"use": "official", "family": family, "given": [given]}],
            "gender": gender,
        }
        if birth_date:
            r["birthDate"] = birth_date
        return r

    @staticmethod
    def observation(
        obs_id: Optional[str] = None,
        loinc_code: str = "8310-5",
        value: float = 37.0,
        unit: str = "Cel",
        patient_id: str = "patient-1",
        status: str = "final",
    ) -> Dict[str, Any]:
        obs_id = obs_id or str(uuid.uuid4())
        display = LOINC_COMMON.get(loinc_code, "Observation")
        return {
            "resourceType": "Observation",
            "id": obs_id,
            "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-clinical-result"]},
            "status": status,
            "code": {
                "coding": [{"system": "http://loinc.org", "code": loinc_code, "display": display}],
                "text": display,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
        }

    @staticmethod
    def encounter(
        enc_id: Optional[str] = None,
        patient_id: str = "patient-1",
        status: str = "finished",
        encounter_class: str = "AMB",
    ) -> Dict[str, Any]:
        enc_id = enc_id or str(uuid.uuid4())
        return {
            "resourceType": "Encounter",
            "id": enc_id,
            "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-encounter"]},
            "status": status,
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": encounter_class,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "period": {
                "start": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }

    @staticmethod
    def condition(
        cond_id: Optional[str] = None,
        patient_id: str = "patient-1",
        snomed_code: str = "73211009",
        display: str = "Diabetes mellitus",
        clinical_status: str = "active",
    ) -> Dict[str, Any]:
        cond_id = cond_id or str(uuid.uuid4())
        return {
            "resourceType": "Condition",
            "id": cond_id,
            "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-problems-health-concerns"]},
            "clinicalStatus": {
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": clinical_status}],
            },
            "code": {
                "coding": [{"system": "http://snomed.info/sct", "code": snomed_code, "display": display}],
                "text": display,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
        }

    @staticmethod
    def bundle(
        resources: Optional[List[Dict[str, Any]]] = None,
        bundle_type: str = "collection",
        bundle_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        bundle_id = bundle_id or str(uuid.uuid4())
        entries = []
        for r in (resources or []):
            rtype = r.get("resourceType", "Resource")
            rid = r.get("id", "")
            entries.append({
                "fullUrl": f"urn:uuid:{rid}" if rid else f"urn:uuid:{uuid.uuid4()}",
                "resource": r,
            })
        return {
            "resourceType": "Bundle",
            "id": bundle_id,
            "type": bundle_type,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entry": entries,
        }


# ---------------------------------------------------------------------------
# HL7 v2.x to FHIR converter (PID, OBX, PV1 segments)
# ---------------------------------------------------------------------------

class HL7ToFHIRConverter:
    """
    Convert HL7 v2.x message segments to FHIR R4 resources.

    Supports:
    - PID segment → Patient
    - OBX segment → Observation
    - PV1 segment → Encounter
    """

    def convert_pid(self, pid_fields: List[str]) -> Dict[str, Any]:
        """Convert HL7 PID segment fields to FHIR Patient.

        Args:
            pid_fields: List of field values [PID.0, PID.1, PID.2, ...]
                        (index 0 = 'PID', index 3 = Patient ID, etc.)
        """
        def field(n: int, default: str = "") -> str:
            return pid_fields[n] if n < len(pid_fields) else default

        patient_id = field(3).split("^")[0]
        name_parts = field(5).split("^")
        family = name_parts[0] if name_parts else ""
        given = name_parts[1] if len(name_parts) > 1 else ""

        gender_map = {"M": "male", "F": "female", "U": "unknown", "O": "other"}
        gender = gender_map.get(field(8, "U").upper(), "unknown")

        birth_date_raw = field(7)
        birth_date = ""
        if birth_date_raw and len(birth_date_raw) >= 8:
            bd = birth_date_raw[:8]
            birth_date = f"{bd[:4]}-{bd[4:6]}-{bd[6:8]}"

        return FHIRTemplates.patient(
            patient_id=patient_id or None,
            family=family,
            given=given,
            gender=gender,
            birth_date=birth_date,
        )

    def convert_obx(
        self,
        obx_fields: List[str],
        patient_id: str = "patient-1",
    ) -> Dict[str, Any]:
        """Convert HL7 OBX segment to FHIR Observation."""
        def field(n: int, default: str = "") -> str:
            return obx_fields[n] if n < len(obx_fields) else default

        obs_type = field(2)
        loinc_parts = field(3).split("^")
        loinc_code = loinc_parts[0]
        obs_display = loinc_parts[1] if len(loinc_parts) > 1 else LOINC_COMMON.get(loinc_code, "Observation")
        raw_value = field(5)
        units = field(6).split("^")[0]
        status_map = {"F": "final", "P": "preliminary", "C": "corrected", "X": "cancelled"}
        # OBX-11 is observation result status; in pipe-delimited, index 11 (0-based)
        # Short segments may have it at index 10 — try both
        status_raw = field(11) or field(10, "F")
        status = status_map.get(status_raw.strip().upper(), "final")

        obs: Dict[str, Any] = {
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "status": status,
            "code": {
                "coding": [{"system": "http://loinc.org", "code": loinc_code, "display": obs_display}],
                "text": obs_display,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        fhir_type = HL7_OBX_TYPE_MAP.get(obs_type, "valueString")
        if fhir_type == "valueQuantity":
            try:
                obs[fhir_type] = {
                    "value": float(raw_value),
                    "unit": units,
                    "system": "http://unitsofmeasure.org",
                    "code": units,
                }
            except ValueError:
                obs["valueString"] = raw_value
        elif fhir_type == "valueCodeableConcept":
            parts = raw_value.split("^")
            obs[fhir_type] = {
                "coding": [{"code": parts[0], "display": parts[1] if len(parts) > 1 else parts[0]}],
            }
        else:
            obs["valueString"] = raw_value

        return obs

    def convert_pv1(
        self,
        pv1_fields: List[str],
        patient_id: str = "patient-1",
    ) -> Dict[str, Any]:
        """Convert HL7 PV1 segment to FHIR Encounter."""
        def field(n: int, default: str = "") -> str:
            return pv1_fields[n] if n < len(pv1_fields) else default

        class_map = {"I": "IMP", "O": "AMB", "E": "EMER", "P": "PRENC", "R": "AMB"}
        enc_class = class_map.get(field(2, "O").upper(), "AMB")
        status_map = {"A": "in-progress", "P": "planned", "D": "finished"}
        status = status_map.get(field(44, "D").upper(), "finished")

        return FHIRTemplates.encounter(
            patient_id=patient_id,
            status=status,
            encounter_class=enc_class,
        )


# ---------------------------------------------------------------------------
# Query helper
# ---------------------------------------------------------------------------

FHIR_QUERY_PATTERNS = [
    (r"patient.*name.*(\w+)", "GET /Patient?name={0}"),
    (r"patient.*id.*(\w+)",   "GET /Patient/{0}"),
    (r"observations?.*patient.*(\w+)", "GET /Observation?patient={0}"),
    (r"encounter.*patient.*(\w+)", "GET /Encounter?patient={0}"),
    (r"condition.*patient.*(\w+)", "GET /Condition?patient={0}"),
    (r"medic.*patient.*(\w+)", "GET /MedicationRequest?patient={0}"),
    (r"all resources.*patient.*(\w+)", "GET /Patient/{0}/$everything"),
    (r"bundle.*patient.*(\w+)", "GET /Patient/{0}/$everything"),
    (r"latest obs.*(\w+)", "GET /Observation?patient={0}&_sort=-date&_count=1"),
]


def natural_language_query(text: str) -> str:
    """Map a natural language question to an approximate FHIR REST query.

    Args:
        text: Natural language query string

    Returns:
        FHIR REST API query string suggestion
    """
    lower = text.lower().strip()
    for pattern, template in FHIR_QUERY_PATTERNS:
        m = re.search(pattern, lower)
        if m and m.groups():
            group = m.group(1)
            return template.format(group)
        elif m:
            return template.format("?")
    return f"GET /[ResourceType]?[parameter]=[value]  (could not parse: '{text}')"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="fhir-ai-copilot",
        description="FHIR R4 AI Copilot: validate, generate, convert, and query",
    )
    sub = parser.add_subparsers(dest="command")

    # validate
    v = sub.add_parser("validate", help="Validate a FHIR JSON resource file")
    v.add_argument("file", help="Path to FHIR JSON resource")
    v.add_argument("--json", action="store_true", dest="json_out")
    v.add_argument("--exit-code", action="store_true")

    # template
    t = sub.add_parser("template", help="Generate a FHIR resource template")
    t.add_argument("type", choices=["Patient", "Observation", "Encounter", "Condition", "Bundle"])
    t.add_argument("--id", default=None, dest="res_id")

    # convert
    c = sub.add_parser("convert", help="Convert HL7 segment to FHIR (pipe input)")
    c.add_argument("segment", choices=["PID", "OBX", "PV1"])
    c.add_argument("data", help="Pipe-delimited HL7 segment string")
    c.add_argument("--patient-id", default="patient-1")

    # query
    q = sub.add_parser("query", help="Natural language → FHIR REST query")
    q.add_argument("text", nargs="+")

    # list-types
    sub.add_parser("list-types", help="List all supported FHIR resource types")

    # demo
    sub.add_parser("demo", help="Run a built-in demo")

    args = parser.parse_args(argv)

    if args.command == "validate":
        try:
            with open(args.file, encoding="utf-8") as f:
                resource = json.load(f)
        except Exception as e:
            print(f"❌ {e}", file=sys.stderr)
            return 1
        report = FHIRValidator().validate(resource)
        if args.json_out:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            _print_validation_report(report)
        return 1 if (args.exit_code and not report.is_valid) else 0

    elif args.command == "template":
        templates = FHIRTemplates()
        rtype = args.type
        if rtype == "Patient":
            r = templates.patient(patient_id=args.res_id)
        elif rtype == "Observation":
            r = templates.observation(obs_id=args.res_id)
        elif rtype == "Encounter":
            r = templates.encounter(enc_id=args.res_id)
        elif rtype == "Condition":
            r = templates.condition(cond_id=args.res_id)
        else:  # Bundle
            r = templates.bundle(bundle_id=args.res_id)
        print(json.dumps(r, indent=2))
        return 0

    elif args.command == "convert":
        fields = args.data.split("|")
        converter = HL7ToFHIRConverter()
        if args.segment == "PID":
            r = converter.convert_pid(fields)
        elif args.segment == "OBX":
            r = converter.convert_obx(fields, patient_id=args.patient_id)
        else:
            r = converter.convert_pv1(fields, patient_id=args.patient_id)
        print(json.dumps(r, indent=2))
        return 0

    elif args.command == "query":
        text = " ".join(args.text)
        result = natural_language_query(text)
        print(f"\n💬 Query: {text}")
        print(f"🔎 FHIR:  {result}\n")
        return 0

    elif args.command == "list-types":
        for t in sorted(FHIR_RESOURCE_TYPES):
            req = REQUIRED_FIELDS.get(t, [])
            print(f"  {t:<30} required: {req if req else '(none beyond resourceType)'}")
        return 0

    elif args.command == "demo":
        print("\n=== FHIR AI Copilot Demo ===\n")

        print("1. Generate Patient template:")
        p = FHIRTemplates.patient(family="Smith", given="Alice", gender="female", birth_date="1985-06-15")
        print(json.dumps(p, indent=2)[:400], "...\n")

        print("2. Validate Patient:")
        report = FHIRValidator().validate(p)
        _print_validation_report(report)

        print("3. Convert HL7 PID segment:")
        conv = HL7ToFHIRConverter()
        pid = "PID|1||PAT-001^^^MRN||Doe^John||19900301|M".split("|")
        fhir_patient = conv.convert_pid(pid)
        print(json.dumps(fhir_patient, indent=2)[:300], "...\n")

        print("4. Natural language query:")
        for q in [
            "get observations for patient pat-123",
            "show all resources for patient P001",
        ]:
            print(f"  Q: {q}")
            print(f"  A: {natural_language_query(q)}\n")
        return 0

    else:
        parser.print_help()
        return 0


def _print_validation_report(report: ValidationReport) -> None:
    print("\n" + "=" * 60)
    print("  FHIR R4 Validation Report")
    print("=" * 60)
    print(f"  {report.summary()}")
    print("=" * 60)
    if not report.issues:
        print("  ✅ No issues found!")
    else:
        by_sev = {s: [] for s in Severity}
        for issue in report.issues:
            by_sev[issue.severity].append(issue)
        for sev in [Severity.ERROR, Severity.WARNING, Severity.INFO]:
            grp = by_sev[sev]
            if grp:
                print(f"\n  {sev.value}S ({len(grp)}):")
                print("  " + "-" * 56)
                for issue in grp:
                    print(issue)
    print("=" * 60 + "\n")


if __name__ == "__main__":
    sys.exit(main())
