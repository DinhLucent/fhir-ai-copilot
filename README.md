# fhir-ai-copilot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)
[![FHIR R4](https://img.shields.io/badge/FHIR-R4-green.svg)](https://hl7.org/fhir/R4/)

> CLI copilot for FHIR R4 resources. Validates patient data, generates resource templates, and converts HL7 v2.x segments to FHIR-compliant JSON.

## Features

- **FHIR Validator** — Conformance checking for 20+ R4 resource types and status codes
- **HL7 Converter** — Transforms PID, OBX, and PV1 segments to valid FHIR resources
- **Resource Templates** — One-click generation for Patient, Observation, Bundle, and more
- **NL Query Helper** — Search FHIR endpoints using natural language pattern matching
- **Testing Engine** — Integrated pytest suite with 50+ healthcare-specific test cases

## Tech Stack

- **Core**: Python 3.9+
- **Standard**: HL7 FHIR R4 (Release 4.0.1)
- **Testing**: pytest

## Project Structure

```
fhir-ai-copilot/
├── src/
│   └── main.py          # FHIR validator, converter, and CLI
├── tests/
│   └── test_copilot.py   # pytest suite
├── examples/             # Sample FHIR/HL7 data
└── README.md
```

## Getting Started

1. Clone the repository:
   ```bash
   git clone https://github.com/DinhLucent/fhir-ai-copilot.git
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run validation:
   ```bash
   python src/main.py validate examples/patient.json
   ```

## Demo

Convert an HL7 PID segment to FHIR:
```bash
python src/main.py convert PID "PID|1||PAT-001||Doe^John||19900101|M"
```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---
Built by [DinhLucent](https://github.com/DinhLucent)
