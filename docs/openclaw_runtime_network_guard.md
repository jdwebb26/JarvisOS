# OpenClaw Runtime Network Guard

The installed OpenClaw CLI/runtime can crash in this environment before gateway and health commands complete because `os.networkInterfaces()` throws `ERR_SYSTEM_ERROR` from Node's `uv_interface_addresses`.

Installed file patched:

- `~/.npm-global/lib/node_modules/openclaw/dist/auth-profiles-iXW75sRj.js`

Functions guarded:

- `listTailnetAddresses()`
- `pickPrimaryLanIPv4()`

Required soft-fail behavior:

- if `os.networkInterfaces()` throws in `listTailnetAddresses()`, return `{ ipv4: [], ipv6: [] }`
- if `os.networkInterfaces()` throws in `pickPrimaryLanIPv4()`, return with no value

Reapply or verify from the repo:

```bash
python3 scripts/openclaw_specialization_bridge.py
python3 scripts/openclaw_specialization_bridge.py --apply
```

The helper:

- verifies whether the installed runtime network guard is present
- reapplies it if missing
- writes a timestamped backup under `.hotfix-openclaw/specialization-bridge-<timestamp>/`
- prints `backup_dir` and the patched installed file path

Manual verification command:

```bash
openclaw gateway --help
```

Expected result:

- the command completes without crashing from `uv_interface_addresses` or `os.networkInterfaces()`
