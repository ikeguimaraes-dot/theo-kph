# OS S · Theo

Prepared from deployed commit e755c18f30e02edeb685e5fdb762f2d070f9b49f.
Signature validation uses the exact configured public URL and the Twilio SDK. Invalid signature returns 403 before reading conversations or calling the model. /send and /chat require X-API-Key matching THEO_INTERNAL_TOKEN; missing configuration fails closed (503). Existing browser callers must use an authenticated server proxy; never put this key in NEXT_PUBLIC variables.

MessageSid is claimed atomically in ai1_bot_webhook_receipts. Duplicate deliveries return empty TwiML; a provider-ambiguous execution is not retried. Conversation assumed by an operator is checked before generation and again before replying. Operator history becomes assistant only at the model boundary.

6 local tests pass, including HTTP invalid signature 403, valid signed empty delivery 200 with zero inference, missing API key 401, dedupe and takeover. No messages sent in verification.

Deployment and live verification are recorded after release. Repository privacy remains pending: installed GitHub connector does not expose repository visibility mutation. Do not claim private until verified.
