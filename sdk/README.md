# marketmirror (Python SDK)

```bash
pip install -e sdk            # from the repo root
```

```python
from marketmirror import MarketMirror

mm = MarketMirror("http://localhost:5001", repo="/path/to/market-mirror")

profile = mm.understand(text=open("scenarios/acme/brief.md").read(), url="https://acme.example", name="Acme")
mm.quickstart({"brand": "Acme", "product": profile["one_liner"], "buyers": "parents in Manila", "tests": "ads, price"}, run=False)
stage1 = mm.market_test("scenarios/acme/market_test.json")       # builds the people, stops before spending
# ... set "approve_spend": true and "simulation_id" in the config, then:
done = mm.market_test("scenarios/acme/market_test.json")
res = mm.results("mirofish_runs/acme")
print(res["decision"], res["market_report"]["action_plan"])

ft = mm.feed_test(done["simulation_id"], creatives=[{"id": "a", "platform": "instagram", "text": "..."}], seeds=3)
pred = mm.predict(res, ft, brand="Acme", targets={"ctr": 2.0})
mm.push_context(done["simulation_id"], "A competitor dropped its price today", source="news")
```

REST methods map 1:1 to `docs/API.md`; `cli(...)` runs any `mirofish.py` command inside the repo. Long jobs are awaited by default (`wait=False` returns the task id).
