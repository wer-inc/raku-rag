# raku-rag Python SDK

Small stdlib-only client for the `/v1` API facade.

```python
from raku_rag_sdk import RakuRagClient, make_user_token

token = make_user_token(
    tenant_id="demo",
    user_id="alice",
    groups=["maintenance"],
    roles=["reader"],
)

client = RakuRagClient(
    base_url="http://localhost:3000/v1",
    api_key="local-dev-key",
    user_token=token,
)

answer = client.answer("What is the pump maintenance interval?", collection_id="manuals")
print(answer["status"], answer.get("text"))
```

The SDK accepts an injected transport for tests and custom runtimes. Production callers can pass a
real `X-User-Token` issued by their identity boundary instead of using `make_user_token`.
