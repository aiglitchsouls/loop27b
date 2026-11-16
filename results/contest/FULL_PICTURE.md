# 27B contest run: the full picture

_Written 2026-11-16 06:54 by budget_rerun.py. Model: Qwen3.8-27B, Q4_K_M, on the RTX 4060 (8 GB) with llama.cpp. One try per problem._

## Official scores (main run, 28,000-token thinking budget)

| Test | Score | Notes |
|---|---|---|
| AIME 2026 | **29/30 = 96.7%** | 30/30 done |
| HMMT Feb 2026 | **28/33 = 84.8%** | 33/33 done; 29/33 = 87.9% counting answers equal in value to the key |
| HMMT Feb 2026, counting the bigger-budget rerun wins (8, 18) | **30/33 = 90.9%** | 31/33 = 93.9% also counting answers equal in value to the key. Mixed setup: only the misses got the 48k budget, so this is an upper estimate, not a clean score |
| IFEval (thinking off) | **80.2% prompt-strict** | 541/541 done; prompt-loose 84.3%, instruction-strict 86.3%, instruction-loose 89.6% |

### Every math miss

| Test | # | Model said | Key | Ran out of thinking budget? |
|---|---|---|---|---|
| AIME 2026 | 20 | `277285` | `190` | no |
| HMMT Feb 2026 | 7 (same value as key) | ` \frac{\sqrt[3]{163-\frac{10}{3}\sqrt6}}{3} + \omega\sqrt...` | `(3+\sqrt{6})^{-1/3}` | yes |
| HMMT Feb 2026 | 8 | `200` | `279` | yes |
| HMMT Feb 2026 | 17 | `812` | `1574` | yes |
| HMMT Feb 2026 | 18 | `16928` | `6992` | yes |
| HMMT Feb 2026 | 20 | `1100` | `20460` | yes |

## Bigger thinking budget rerun (diagnostic, not a score)

Only the misses that ran out of thinking budget, rerun once with a bigger budget. This tells us whether they were short of thinking room. It must **not** be added to the score: rerunning only the failures with extra help would inflate it.

| Test | # | Key | Old answer | New answer | Right now? | Tokens | Ran out again? | Time |
|---|---|---|---|---|---|---|---|---|
| HMMT Feb 2026 | 8 | `279` | `200` | `279` | **yes** | 17,472 of 48,000 | no | 1.3 h |
| HMMT Feb 2026 | 17 | `1574` | `812` | `1572` | no | 49,061 of 48,000 | yes | 4.3 h |
| HMMT Feb 2026 | 18 | `6992` | `16928` | `6992` | **yes** | 49,488 of 48,000 | yes | 4.2 h |
| HMMT Feb 2026 | 20 | `20460` | `1100` | `1100` | no | 48,715 of 48,000 | yes | 4.5 h |

**Fixed by more thinking: 2 of 4 rerun so far (4 to rerun in total).**

## How to read this

- **Published numbers are not like-for-like.** The benchlm.ai AIME 2026 list (34 models, all lab-reported) typically uses several tries averaged and 64k-128k thinking. We used one try, 28k thinking, and a compressed (Q4) model on an 8 GB card. For reference there: Qwen3.6-27B 94.1%, Kimi K2.6 96.4%, GLM-5.2 99.2% (top).
- **One problem is 3.3 points on AIME (30 problems) and 3.0 on HMMT (33).** A rerun could easily move the score by a problem either way.
- **The answer checker is strict about form.** HMMT 7 was marked wrong but its answer equals the key's value to 15 decimal places; it is shown both ways above.
- **The rerun is a diagnosis.** If misses turn right with more room, the 28k cap cost points; if not, the model was simply wrong on those.
