# Contributing

Contributions are welcome when they remain copyright-safe and deterministic.

Please do not submit:

- extracted commercial game text or assets;
- API keys, tokens, or private prompts containing proprietary data;
- broad automatic translation replacements presented as QA;
- validators whose runtime assumptions are not documented.

For code changes:

1. add or update standard-library unit tests;
2. run `python -m unittest discover -s tests -v`;
3. run the synthetic demo;
4. document new schema assumptions and failure modes;
5. keep linguistic generation outside deterministic validator code.
