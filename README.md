# fhir-ai-copilot

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python)
![Tests](https://img.shields.io/badge/Tests-51_passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)

A professional FHIR R4 (Fast Healthcare Interoperability Resources) engine for data engineers. It provides high-speed validation, resource templating, legacy HL7 v2.x conversion, and a natural language query helper.

## What is FHIR?

FHIR is the global standard for exchanging healthcare information electronically. It defines a set of "Resources" (Patients, Observations, Encounters) represented as JSON/XML. 

Modern healthcare AI depends on clean, valid FHIR data. This tool ensures your resources meet the R4 specification before they reach the server.

## Quick Start

### Validate a FHIR resource

```bash
python -m src.main validate my_patient.json
```

### Run the Bundle Doctor

Checks for hanging references within a FHIR Bundle (e.g., an Observation pointing to a Patient ID that isn't in the bundle).

```bash
python -m src.main validate my_bundle.json --doctor
```

## Features

- **FHIR R4 Validation**: Deep validation of resource types, mandatory fields, and state machine transitions (e.g., valid Encounter statuses).
- **HL7 v2.x Conversion**: High-speed mapping of legacy PID, OBX, and PV1 segments to valid FHIR R4 resources.
- **Natural Language Query**: Map human-readable questions directly to FHIR REST API paths.
- **Resource Templates**: Generate compliant skeletons for 20+ resource types.
- **Zero-Dependency**: Built entirely on the Python standard library for maximum portability.

## How it works — module by module

### `src/main.py` — Core Logic & CLI

The central hub for validation and conversion logic.

#### Programmatic Conversion

Convert a legacy HL7 pipe-delimited segment to a FHIR Patient:

```python
from src.main import HL7ToFHIRConverter

conv = HL7ToFHIRConverter()
hl7_pid = "PID|1||PAT-001||Doe^John||19900101|M"

fhir_patient = conv.convert_pid(hl7_pid.split("|"))
print(fhir_patient["resourceType"])  # Patient
print(fhir_patient["gender"])        # male
```

#### Natural Language Queries

Simplify FHIR Search API complexity:

```python
from src.main import natural_language_query

query = natural_language_query("get active medications for patient P001")
# Result: GET /MedicationRequest?patient=P001&status=active
```

## Project Structure

```
fhir-ai-copilot/
├── src/
│   ├── __init__.py
│   └── main.py             # Validator, Templates, Converter, NL Logic
├── tests/
│   ├── test_copilot.py     # 51 tests covering full API surface
│   └── test_placeholder.py
├── docs/                   # Extended documentation
├── examples/               # Usage scripts
├── requirements.txt
├── LICENSE
└── README.md
```

## Installation

```bash
git clone https://github.com/DinhLucent/fhir-ai-copilot.git
cd fhir-ai-copilot
pip install -r requirements.txt
```

No external dependencies required.

## Running Tests

```bash
python -m pytest tests/test_copilot.py -v
```

## License

MIT License — see [LICENSE](LICENSE)

---
Built by [DinhLucent](https://github.com/DinhLucent)
