#!/usr/bin/env bash
# Anti-self-certification reminder hook (PreToolUse on Bash).
# 在偵測到 git commit 時，於 commit 前印出提醒：承載性結論需先經獨立紅隊對抗複審。
# 非阻擋（exit 0）；只是確定性的檢查點提醒。trivial 變更可忽略。
input=$(cat 2>/dev/null)
if printf '%s' "$input" | grep -q 'git commit'; then
  printf '%s\n' "[anti-self-certification] 即將 git commit。若本次含『架構決策／schema 變更／對自身產出的審核／回填設計文件』等承載性結論：請確認已派【未接觸該推理的獨立子代理紅隊（≥2 視角）】對抗複審，且事實主張已查證 primary source（未查證標 NOT VERIFIED）。詳見 CLAUDE.md『審核獨立性』。trivial 變更可忽略此提醒。" >&2
fi
exit 0
