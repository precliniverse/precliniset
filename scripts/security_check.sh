#!/bin/bash
# Precliniverse Security Check Script
# This script runs static analysis and dependency auditing.

echo "========================================="
echo "🛡️  Running Precliniverse Security Audit"
echo "========================================="

# 1. Bandit (Static Analysis)
echo -e "\n🔍 Running Bandit (Static Code Analysis)..."
if command -v bandit &> /dev/null
then
    bandit -r app/ -ll
else
    echo "⚠️  Bandit not found. Skipping. (pip install bandit)"
fi

# 2. Pip-Audit (Dependency Analysis)
echo -e "\n📦 Running Pip-Audit (Vulnerability Scanner)..."
if command -v pip-audit &> /dev/null
then
    pip-audit
else
    echo "⚠️  Pip-Audit not found. Skipping. (pip install pip-audit)"
fi

# 3. Custom SSRF Logic Check
echo -e "\n🛠️  Running Custom Security Logic Tests..."
python verify_security.py

echo -e "\n✅ Audit Complete."
