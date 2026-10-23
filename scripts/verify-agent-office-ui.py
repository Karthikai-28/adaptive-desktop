#!/usr/bin/env python3
"""Drive the Agent Office page in headless Chrome against a throwaway server: Mission Control's detail view,
live verdict updates, saving a workflow, and the operator key. Spends no quota (the office stays paused).

    PYTHONPATH=.local/office-pydeps scripts/verify-agent-office-ui.py   (run by scripts/verify-agent-office.sh)
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

REPO = str(Path(__file__).resolve().parents[1])
APP = f"{REPO}/services/agent-office"
PORT, DEBUG = 8798, 9333
B = f"http://127.0.0.1:{PORT}"


def call(method, path, body=None, key=None):
    headers = {"Content-Type": "application/json", "X-Office": "1"}
    if key:
        headers["X-Office-Operator"] = key
    req = urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


async def main(tmp):
    env = dict(os.environ, OFFICE_STATE=f"{tmp}/state", OFFICE_PORT=str(PORT), OFFICE_NO_STUDY="1",
               OFFICE_NO_REPO_SCAN="1", PYTHONPATH=f"{REPO}/.local/office-pydeps")
    server = subprocess.Popen([sys.executable, f"{APP}/server.py"], env=env, stdout=subprocess.DEVNULL,
                              stderr=open(f"{tmp}/server.log", "w"))
    chrome = None
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(B + "/api/state", timeout=1); break
            except OSError:
                time.sleep(0.25)
        call("POST", "/api/settings", {"paused": True})
        key = open(f"{tmp}/state/data/operator.key").read().strip()
        m = call("POST", "/api/missions", {"agent": "maya", "title": "UI mission", "objective": "Check the UI",
                                           "criteria": ["first", "second"]})
        call("POST", "/api/workflows", {"id": "arm", "title": "Arm", "objective": "o", "criteria": ["c"],
                                        "agent": "maya", "risk": "hardware"})
        chrome = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={DEBUG}",
                                   f"--user-data-dir={tmp}/chrome", "--no-first-run", "--disable-gpu", B + "/"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = None
        for _ in range(60):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG}/json", timeout=1).read())
                target = next((p for p in pages if p.get("type") == "page" and p["url"].startswith(B)), None)
                if target:
                    break
            except OSError:
                pass
            time.sleep(0.25)
        assert target, "Chrome did not open the office page"
        async with websockets.connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
            seq, errors = [0], []

            async def ev(expr):
                seq[0] += 1
                await ws.send(json.dumps({"id": seq[0], "method": "Runtime.evaluate",
                                          "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("method") == "Runtime.exceptionThrown":
                        errors.append(msg["params"]["exceptionDetails"])
                    if msg.get("id") == seq[0]:
                        r = msg["result"]
                        if "exceptionDetails" in r:
                            raise AssertionError(f"{expr[:80]}: {r['exceptionDetails']}")
                        return r["result"].get("value")

            await ws.send(json.dumps({"id": 0, "method": "Runtime.enable"}))
            for _ in range(40):
                if await ev("!!document.querySelector('#btnMissions') && !!document.querySelector('.desk, #board, body')"):
                    break
                await asyncio.sleep(0.25)
            await asyncio.sleep(1)
            await ev("true")
            assert not errors, "page errors on load: " + json.dumps(
                [e.get("exception", {}).get("description", e.get("text")) for e in errors])
            await ev("window.confirm = () => true; window.__prompts = []; "
                     "window.prompt = (q) => { window.__prompts.push(q); return window.__answer || null; }; true")
            async def wait_for(expr, what):
                for _ in range(60):
                    if await ev(expr):
                        return
                    await asyncio.sleep(0.25)
                raise AssertionError(f"timed out waiting for {what}: " + str(await ev("document.querySelector('#modal')?.innerText")) + " errors=" + json.dumps([e.get("exception", {}).get("description", e.get("text")) for e in errors])[:1500] + " body=" + str(await ev("document.body.innerText.slice(0, 300)")))

            def click(selector, text):
                return ev(f"(() => {{ const b = [...document.querySelectorAll({json.dumps(selector)})].find(x => x.innerText.includes({json.dumps(text)})); if (!b) return false; b.click(); return true; }})()")

            modal = "document.querySelector('#modal').innerText"
            # the office is paused: the top bar offers Resume and says so (not clicked: that would start agents)
            await wait_for("document.querySelector('#btnPause').classList.contains('resume') && "
                           "document.querySelector('#quota').innerText.includes('Office paused')", "paused top bar")
            # mission detail shows numbered criteria, risk and author
            assert await click("#btnMissions", "")
            await wait_for("!!document.querySelector('.mission-card')", "mission list")
            assert await click(".mission-card", "UI mission")
            await wait_for(f"{modal}.includes('C1 · first')", "mission detail")
            text = await ev(modal)
            assert "C2 · second" in text and "Risk" in text and "read" in text and "Started by" in text, text
            # live updates: the server judges the finished work and the open detail follows without reopening
            import sqlite3
            tid = m["tasks"][0]["id"]
            db = sqlite3.connect(f"{tmp}/state/data/office.db")
            db.execute("UPDATE tasks SET status='done', result=? WHERE id=?", ("Done.\nC1: PASS - pytest 3 passed", tid))
            db.commit(); db.close()
            call("POST", f"/api/tasks/{tid}/cancel")            # any task event re-derives the mission
            await wait_for(f"{modal}.includes('unverified')", "live verdict update")
            text = await ev(modal)
            assert "✓" in text and "pytest 3 passed" in text and "?" in text and "C2" in text, text
            assert await ev("[...document.querySelectorAll('#modal button')].filter(b => b.innerText.includes('Cancel mission')).every(b => b.style.display === 'none')")
            # saving the mission as a workflow copies it server-side; replacing it later needs the key
            assert await click("#modal button", "Save workflow")
            await wait_for(f"{modal}.includes('Risk class')", "save workflow form")
            assert await click("#modal button", "Save workflow")
            await wait_for("!!document.querySelector('#modal h2') && document.querySelector('#modal h2').innerText.includes('Workflow library')", "workflow library")
            w = call("GET", "/api/workflows/ui-mission")
            assert w["criteria"] == ["first", "second"] and w["objective"] == "Check the UI" and w["created_by"] == "operator", w
            # a wrong stored operator key is refused and forgotten
            await ev("localStorage.setItem('office.operatorKey', 'wrong'); true")
            assert await click(".mission-card", "Arm") is not False
            await ev("[...document.querySelectorAll('#modal .mission-card')].find(c => c.innerText.includes('Arm')).querySelector('button').click(); true")
            await wait_for("localStorage.getItem('office.operatorKey') === null", "wrong key to be dropped")
            # with no key stored, approving asks for it once, keeps it, and the run is recorded as approved
            await ev("window.__answer = " + json.dumps(key) + "; window.__prompts = []; true")
            await ev("[...document.querySelectorAll('#modal .mission-card')].find(c => c.innerText.includes('Arm')).querySelector('button').click(); true")
            await wait_for(f"{modal}.includes('Approved')", "approved hardware mission")
            assert await ev("window.__prompts.length") == 1 and await ev("localStorage.getItem('office.operatorKey')") == key
            assert errors == [], errors
        print("ui checks passed")
    finally:
        if chrome:
            chrome.terminate()
            chrome.wait(10)
        server.terminate()
        server.wait(10)


tmp = tempfile.mkdtemp()
try:
    asyncio.run(main(tmp))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
