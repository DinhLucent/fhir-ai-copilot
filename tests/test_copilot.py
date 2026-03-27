"""Tests for fhir-ai-copilot — pytest suite"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from main import (
    FHIR_RESOURCE_TYPES,
    FHIRIssue,
    FHIRTemplates,
    FHIRValidator,
    HL7ToFHIRConverter,
    Severity,
    ValidationReport,
    natural_language_query,
    main as cli_main,
)


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def valid_patient():
    return FHIRTemplates.patient(
        patient_id="patient-001",
        family="Smith", given="Alice",
        gender="female", birth_date="1985-06-15",
    )


@pytest.fixture
def valid_observation():
    return FHIRTemplates.observation(
        obs_id="obs-001", loinc_code="8310-5", value=37.0,
        unit="Cel", patient_id="patient-001", status="final",
    )


@pytest.fixture
def valid_encounter():
    return FHIRTemplates.encounter(
        enc_id="enc-001", patient_id="patient-001",
        status="finished", encounter_class="AMB",
    )


@pytest.fixture
def valid_condition():
    return FHIRTemplates.condition(
        cond_id="cond-001", patient_id="patient-001",
        snomed_code="73211009", display="Diabetes mellitus",
    )


# ----------------------------------------------------------------- FHIRValidator

class TestFHIRValidatorBasics:
    def setup_method(self):
        self.v = FHIRValidator()

    def test_valid_patient(self, valid_patient):
        r = self.v.validate(valid_patient)
        assert r.is_valid

    def test_valid_observation(self, valid_observation):
        r = self.v.validate(valid_observation)
        assert r.is_valid

    def test_valid_encounter(self, valid_encounter):
        r = self.v.validate(valid_encounter)
        assert r.is_valid

    def test_valid_condition(self, valid_condition):
        r = self.v.validate(valid_condition)
        assert r.is_valid

    def test_missing_resource_type(self):
        r = self.v.validate({"id": "abc"})
        codes = [i.code for i in r.errors]
        assert "MISSING_RESOURCE_TYPE" in codes

    def test_unknown_resource_type(self):
        r = self.v.validate({"resourceType": "FakeResource", "id": "x"})
        codes = [i.code for i in r.errors]
        assert "UNKNOWN_RESOURCE_TYPE" in codes

    def test_missing_id_warning(self):
        p = FHIRTemplates.patient()
        del p["id"]
        r = self.v.validate(p)
        codes = [i.code for i in r.warnings]
        assert "MISSING_ID" in codes

    def test_invalid_id_format(self, valid_patient):
        valid_patient["id"] = "has space!"
        r = self.v.validate(valid_patient)
        codes = [i.code for i in r.errors]
        assert "INVALID_ID_FORMAT" in codes

    def test_missing_required_encounter_status(self):
        enc = {"resourceType": "Encounter", "id": "e1", "class": {"code": "AMB"}}
        r = self.v.validate(enc)
        codes = [i.code for i in r.errors]
        assert "MISSING_REQUIRED_FIELD" in codes

    def test_invalid_encounter_status(self, valid_encounter):
        valid_encounter["status"] = "flying"
        r = self.v.validate(valid_encounter)
        codes = [i.code for i in r.errors]
        assert "INVALID_STATUS" in codes

    def test_invalid_patient_birthdate(self, valid_patient):
        valid_patient["birthDate"] = "15-06-1985"  # Wrong format
        r = self.v.validate(valid_patient)
        codes = [i.code for i in r.errors]
        assert "INVALID_DATE_FORMAT" in codes

    def test_invalid_patient_gender(self, valid_patient):
        valid_patient["gender"] = "nonbinary"
        r = self.v.validate(valid_patient)
        codes = [i.code for i in r.errors]
        assert "INVALID_GENDER" in codes

    def test_missing_profile_info(self):
        p = FHIRTemplates.patient()
        del p["meta"]
        r = self.v.validate(p)
        info_codes = [i.code for i in r.issues if i.severity == Severity.INFO]
        assert "MISSING_PROFILE" in info_codes

    def test_report_summary_valid(self, valid_patient):
        r = self.v.validate(valid_patient)
        assert "VALID" in r.summary()

    def test_report_to_dict_keys(self, valid_patient):
        r = self.v.validate(valid_patient)
        d = r.to_dict()
        assert "valid" in d
        assert "resource_type" in d
        assert "issues" in d


# ----------------------------------------------------------------- FHIRTemplates

class TestFHIRTemplates:
    def test_patient_has_name(self, valid_patient):
        assert "name" in valid_patient
        assert valid_patient["name"][0]["family"] == "Smith"

    def test_observation_has_value(self, valid_observation):
        assert "valueQuantity" in valid_observation
        assert valid_observation["valueQuantity"]["value"] == 37.0

    def test_encounter_has_class(self, valid_encounter):
        assert "class" in valid_encounter
        assert valid_encounter["class"]["code"] == "AMB"

    def test_condition_has_code(self, valid_condition):
        assert "code" in valid_condition

    def test_bundle_wraps_resources(self, valid_patient, valid_observation):
        bundle = FHIRTemplates.bundle(
            resources=[valid_patient, valid_observation],
            bundle_type="collection",
        )
        assert bundle["resourceType"] == "Bundle"
        assert len(bundle["entry"]) == 2

    def test_bundle_empty(self):
        bundle = FHIRTemplates.bundle()
        assert bundle["entry"] == []

    def test_all_templates_pass_validation(self, valid_patient, valid_observation, valid_encounter, valid_condition):
        v = FHIRValidator()
        for r in [valid_patient, valid_observation, valid_encounter, valid_condition]:
            report = v.validate(r)
            assert report.is_valid, f"{r['resourceType']} should be valid: {report.errors}"


# ----------------------------------------------------------------- HL7ToFHIRConverter

class TestHL7PIDConverter:
    def setup_method(self):
        self.conv = HL7ToFHIRConverter()

    def _pid(self, fields_str: str) -> list:
        return fields_str.split("|")

    def test_basic_conversion(self):
        fields = self._pid("PID|1||PAT-001^^^MRN||Doe^John||19900301|M")
        p = self.conv.convert_pid(fields)
        assert p["resourceType"] == "Patient"
        assert p["id"] == "PAT-001"
        assert p["gender"] == "male"
        assert p["birthDate"] == "1990-03-01"

    def test_female_gender(self):
        # PID fields: 0=PID 1=SetID 2=PatientID 3=PatientID 4= 5=Name 6= 7=DOB 8=Sex
        fields = self._pid("PID|1||P2||Doe^Jane||19850101|F")
        p = self.conv.convert_pid(fields)
        assert p["gender"] == "female"

    def test_unknown_gender(self):
        fields = self._pid("PID|1||P3|||Test^User||19700101|U")
        p = self.conv.convert_pid(fields)
        assert p["gender"] == "unknown"

    def test_empty_pid(self):
        # Should not crash with minimal fields
        p = self.conv.convert_pid(["PID"])
        assert p["resourceType"] == "Patient"


class TestHL7OBXConverter:
    def setup_method(self):
        self.conv = HL7ToFHIRConverter()

    def _obx(self, fields_str: str) -> list:
        return fields_str.split("|")

    def test_numeric_observation(self):
        fields = self._obx("OBX|1|NM|8310-5^Body temperature^LN||37.5|Cel|35.0-37.5||||F")
        obs = self.conv.convert_obx(fields, patient_id="patient-001")
        assert obs["resourceType"] == "Observation"
        assert "valueQuantity" in obs
        assert obs["valueQuantity"]["value"] == 37.5

    def test_string_observation(self):
        fields = self._obx("OBX|1|ST|99999-1^Comment^LN||Normal findings||||F")
        obs = self.conv.convert_obx(fields)
        assert "valueString" in obs
        assert obs["valueString"] == "Normal findings"

    def test_status_preliminary(self):
        fields = self._obx("OBX|1|NM|8867-4^HR^LN||72|/min||||P")
        obs = self.conv.convert_obx(fields)
        assert obs["status"] == "preliminary"

    def test_codeable_concept_observation(self):
        fields = self._obx("OBX|1|CE|12345-6^Test^LN||M^Male^HL7|||||F")
        obs = self.conv.convert_obx(fields)
        assert "valueCodeableConcept" in obs


class TestHL7PV1Converter:
    def setup_method(self):
        self.conv = HL7ToFHIRConverter()

    def test_inpatient_encounter(self):
        fields = "PV1|1|I".split("|")
        enc = self.conv.convert_pv1(fields, patient_id="pat-1")
        assert enc["resourceType"] == "Encounter"
        assert enc["class"]["code"] == "IMP"

    def test_outpatient_encounter(self):
        fields = "PV1|1|O".split("|")
        enc = self.conv.convert_pv1(fields)
        assert enc["class"]["code"] == "AMB"

    def test_emergency_encounter(self):
        fields = "PV1|1|E".split("|")
        enc = self.conv.convert_pv1(fields)
        assert enc["class"]["code"] == "EMER"


# ----------------------------------------------------------------- NL Query

class TestNaturalLanguageQuery:
    def test_patient_name_query(self):
        r = natural_language_query("get patient by name Smith")
        assert "Patient" in r

    def test_observations_query(self):
        r = natural_language_query("get observations for patient pat123")
        assert "Observation" in r

    def test_all_resources_query(self):
        r = natural_language_query("get all resources for patient P001")
        assert "$everything" in r or "Patient" in r

    def test_unknown_query_graceful(self):
        r = natural_language_query("what is the weather today")
        assert isinstance(r, str) and len(r) > 0


# ----------------------------------------------------------------- CLI

class TestCLI:
    def test_demo_command(self):
        assert cli_main(["demo"]) == 0

    def test_list_types_command(self):
        assert cli_main(["list-types"]) == 0

    def test_no_command(self):
        assert cli_main([]) == 0

    def test_query_command(self):
        assert cli_main(["query", "get patient by name Doe"]) == 0

    def test_template_patient(self, capsys):
        rc = cli_main(["template", "Patient"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["resourceType"] == "Patient"

    def test_template_observation(self, capsys):
        rc = cli_main(["template", "Observation"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["resourceType"] == "Observation"

    def test_template_bundle(self, capsys):
        rc = cli_main(["template", "Bundle"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["resourceType"] == "Bundle"

    def test_validate_valid_file(self, tmp_path, capsys):
        p = FHIRTemplates.patient()
        f = tmp_path / "patient.json"
        f.write_text(json.dumps(p), encoding="utf-8")
        rc = cli_main(["validate", str(f)])
        assert rc == 0

    def test_validate_invalid_file_exit_code(self, tmp_path):
        bad = {"resourceType": "Patient", "id": "p1", "birthDate": "bad-date", "gender": "alien"}
        f = tmp_path / "bad.json"
        f.write_text(json.dumps(bad), encoding="utf-8")
        rc = cli_main(["validate", str(f), "--exit-code"])
        assert rc == 1

    def test_validate_json_output(self, tmp_path, capsys):
        p = FHIRTemplates.patient()
        f = tmp_path / "p.json"
        f.write_text(json.dumps(p), encoding="utf-8")
        cli_main(["validate", str(f), "--json"])
        out = json.loads(capsys.readouterr().out)
        assert "valid" in out

    def test_validate_missing_file(self):
        rc = cli_main(["validate", "no_such_file.json"])
        assert rc == 1

    def test_convert_pid(self, capsys):
        rc = cli_main(["convert", "PID", "PID|1||PAT-1|||Doe^John||19900101|M"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["resourceType"] == "Patient"

    def test_convert_obx(self, capsys):
        rc = cli_main(["convert", "OBX", "OBX|1|NM|8310-5^Temp^LN||37.5|Cel||||F"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["resourceType"] == "Observation"

    def test_convert_pv1(self, capsys):
        rc = cli_main(["convert", "PV1", "PV1|1|O"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["resourceType"] == "Encounter"
