# Zero-State Protocol

Zero-State permanently sanitizes explicitly selected internal storage and leaves
the computer **unprovisioned**: no Ubuntu installation, accounts, applications,
or local user data remain. It is a transfer-or-retirement procedure, not normal
Adaptive Desktop recovery.

It cannot promise that no trace exists outside the internal disks. Firmware,
network logs, cloud services, backups, removable media, and other machines are
separate systems. Revoke sessions and rotate credentials from another trusted
device before handing the computer over.

## Safety model

- The protocol is never automatic or remotely callable.
- It has no default disk: an operator names one whole `/dev/...` disk at a time.
- Its default mode only prints a plan; it changes nothing.
- Destruction is refused when the selected disk backs the running system or has
  any mounted partition.
- Execution requires trusted external boot media, root, an explicit environment
  marker, a supported sanitization method, and a per-disk confirmation phrase.
- It does not reinstall Ubuntu. A successful run leaves the disk blank.

## Prepare

1. Remove or account for every internal drive. The protocol intentionally treats
   each disk separately so it cannot silently erase an unexpected drive.
2. Create and boot trusted external Linux media. Do **not** run from the Ubuntu
   installation being retired.
3. Inspect the intended disk and create a read-only plan:

   ```sh
   ./scripts/zero-state-protocol.sh --disk /dev/nvme0n1 --plan
   ```

4. Read the displayed model, serial, size, and confirmation phrase. Stop if any
   value is unexpected.

### Optional phone arming

A paired phone can say **Zero-State** in Adaptive Link's Ask screen. That
requires the phone's destructive-action confirmation and records an
authenticated arm request for the local audit trail. It is intentionally not
an erase command: it neither reboots the computer nor invokes this script.
Continue only by booting trusted external media and following the Prepare and
Execute steps below.

## Execute

Choose only a method supported by the actual device and its documentation:

- `nvme-crypto-erase` for a supported NVMe controller crypto erase;
- `nvme-block-erase` for a supported NVMe controller block erase;
- `secure-discard` only when the selected device reports secure-discard support.

From the external environment, repeat the command printed by plan mode, for
example:

```sh
sudo env ZERO_STATE_EXTERNAL_BOOT=1 ./scripts/zero-state-protocol.sh \
  --disk /dev/nvme0n1 --method nvme-crypto-erase --execute \
  --confirm 'ZERO-STATE:nvme0n1:SERIAL-FROM-PLAN'
```

NVMe sanitize operates on the controller and can affect every namespace on it.
Do not use it if the controller contains any storage that must survive. Secure
discard can fail when the device does not support it; failure is not permission
to substitute an unsafe method blindly.

For the assurance level and the specific media type, choose clear, purge, or
physical destruction using the organization’s policy and NIST SP 800-88. Once
all intended disks are sanitized, power the machine off. Do not install an OS;
the next owner provisions it independently.
