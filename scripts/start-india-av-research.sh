#!/usr/bin/env bash
set -euo pipefail

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"

office_cli="$ADAPTIVE_REPO/services/agent-office/bin/office"
brief_file="$ADAPTIVE_REPO/docs/INDIA_AV_OFFICE_BRIEF.txt"
plan_file="$ADAPTIVE_REPO/docs/INDIA_AV_RESEARCH_PLAN.md"

if [[ ! -r "$brief_file" || ! -r "$plan_file" ]]; then
    printf '%s\n' 'The project brief or research plan is missing.' >&2
    exit 1
fi

if ! "$office_cli" status >/dev/null 2>&1; then
    systemctl --user start adaptive-agent-office
    for attempt in {1..10}; do
        if "$office_cli" status >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
fi

"$office_cli" status
project_request="$(cat "$brief_file" "$plan_file")"
"$office_cli" ask claude "$project_request" --no-wait
printf '%s\n' \
    'Project brief submitted for manager review and assignment.' \
    'Submission is not confirmation that tasks were created.' \
    'Read the manager reply and task IDs in http://127.0.0.1:8790.'
