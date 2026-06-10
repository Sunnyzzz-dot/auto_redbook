# Publishing Worker

The worker keeps browser state on the local machine and connects to the API server over WebSocket. Each Xiaohongshu account uses a separate persistent Chromium profile under `profiles/{account_id}`.

The worker does not bypass login, CAPTCHA, or platform risk-control pages. If such a page is detected, it reports `requires_human_intervention` and keeps a screenshot for the operator.

## Start

```bash
pip install -r requirements.txt
playwright install chromium
python -m worker.main
```
