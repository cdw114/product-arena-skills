# Minimal invocation on a synthetic passage

This example illustrates the interface with invented data.

Write this line to text.txt:

    Model A scored 28.4 BLEU on the synthetic task.

Write assertions.json:

```json
[{"id":"A1","text":"Model A scored 28.4 BLEU on the synthetic task.","claim_type":"result","subject":"Model A","predicate":"scored","object":"28.4 BLEU","qualifiers":{"magnitude":28.4,"unit":"BLEU","metric":"BLEU","condition":"on the synthetic task"},"quote":"Model A scored 28.4 BLEU on the synthetic task.","relation":"direct","confidence":"high"}]
```

Run from the skill directory with Python 3.8 or later:

```sh
python3 scripts/np_build.py finalise --text text.txt --assertions assertions.json --out example-output --status success
```

The example result has status success and claim A1. The recorded offset can be used
to retrieve the exact source slice. See example-output/result.json and report.md.
