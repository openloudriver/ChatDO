# ChatDO — Northstead Director of Operations

Local dev-time AI that helps maintain Northstead repos
(PrivacyPay, DRR, etc.) using deep agents, planning, and filesystem tools.

- Lives in `/Users/christopher.peck/ChatDO`
- Never ships to users
- Works against local checkouts like `/Users/christopher.peck/privacypay`

## Usage

```bash
cd ~/ChatDO
source .venv/bin/activate  # if using venv

# Example: review Credit Vault contracts in PrivacyPay
python -m chatdo --target privacypay \
  "Review packages/core/grow/creditvault/README.md and related policy/security files.
   List any inconsistencies and propose exact patches."
```

## How you actually use this tomorrow

Once this is wired:

1. You write a *high-level* task for ChatDO, e.g.:

   ```bash
   python -m chatdo --target privacypay \
     "Align Credit Vault README, credit-vault policy JSON, and security/zk/credit-vault-proofs.md.
      Treat README as the behavioral truth. Propose concrete changes to policy and ZK spec if needed."
   ```

2. ChatDO uses:
   - `list_files` to discover files
   - `read_file` to read them
   - `write_todos` internally to plan steps

3. It responds with:
   - A short analysis
   - Proposed diffs / new sections you can copy into Cursor

You still stay in control in Cursor:
- Paste its proposed patch
- Let Cursor's agent review it
- Run tests / linters
- Commit when you are comfortable

