# Localization execution plan

| Order | Pair | Schema | Editable fields | Coordinated context | Risk | Status |
|---:|---|---|---|---|---|---|
| 1 | `example` | `dialogue` | `1:text` | speaker exchanges, repeats | medium | pending |

For each pair:

1. inspect representative rows;
2. record baseline issues;
3. run source-first semantic sweep;
4. run target-language quality sweep;
5. author explicit corrections;
6. rebuild and validate release file;
7. update progress and unresolved items.
