"""Which local process sent a request, so the manager's own `office` calls can't pass as the owner's.

A loopback TCP connection is found in /proc/net/tcp by its client port; its socket inode is then looked
for among the open files of the manager's process tree. The manager runs only `office` commands, which
neither detach nor change their parent, so its calls always come from inside that tree.
"""
import os

LOOPBACK = "0100007F"           # 127.0.0.1 as /proc/net/tcp writes it


def _socket_inode(client_host, client_port, server_port):
    if client_host != "127.0.0.1":
        return None
    local, remote = f"{LOOPBACK}:{client_port:04X}", f"{LOOPBACK}:{server_port:04X}"
    try:
        with open("/proc/net/tcp") as f:
            next(f, None)
            for line in f:
                parts = line.split()
                if len(parts) > 9 and parts[1] == local and parts[2] == remote:
                    return parts[9]
    except OSError:
        pass
    return None


def _children():
    kids = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        kids.setdefault(ppid, []).append(int(name))
    return kids


def owned_by(roots, client_host, client_port, server_port):
    """True when the connection from client_host:client_port belongs to a process in one of the roots' trees."""
    roots = [int(p) for p in roots if p]
    if not roots:
        return False
    inode = _socket_inode(client_host, client_port, server_port)
    if not inode:
        return False
    target, kids, seen, stack = f"socket:[{inode}]", _children(), set(), list(roots)
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        stack += kids.get(pid, [])
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(f"/proc/{pid}/fd/{fd}") == target:
                    return True
            except OSError:
                continue
    return False
