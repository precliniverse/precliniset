# Security Policy

## Supported Versions
| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability
If you discover a security vulnerability within Precliniset, please do not open a public issue.

Create an issue in github

## Security Features
This project implements:
1.  **CSP**: Strict Content Security Policy with Nonces.
2.  **SSRF Protection**: DNS resolution validation for external calls.
3.  **Input Sanitization**: Protection against Excel Formula Injection.
4.  **Audit Trail**: Immutable logging of all data changes (GLP).
