# #985 unit a: the estimate against the real end, 107 finished runs

Harness: `mods/pob-slots/bin/estimate_table_985.py` (logs only, no PoB; the add-on's own `estimate()` called at 25 / 50 / 75 % of each finished run, with only what existed then).
Error = |predicted - actual| / actual, both the time still to go. Before = the code of main (d8eac103), after = this branch.

## Median error

| runs | n | 25 % before | 25 % after | 50 % before | 50 % after | 75 % before | 75 % after |
|---|---|---|---|---|---|---|---|
| all | 107 | 54 % | 23 % | 51 % | 17 % | 47 % | 25 % |
| replay | 84 | 56 % | 16 % | 50 % | 17 % | 38 % | 29 % |
| benchmark | 23 | 44 % | 45 % | 63 % | 21 % | 77 % | 25 % |

A run with no estimate at a moment (no finished build yet) is left out of that moment's median.

## Every run

| run | tag | kind | builds | duration | at | predicted after | how | actual left | error after | error before |
|---|---|---|---|---|---|---|---|---|---|---|
| j-20260927-0359-8b3e | proof35-replay-base | replay | 6 | 66 min | 25 % | нет оценки | - | 50 min | - | - |
| j-20260927-0359-8b3e | proof35-replay-base | replay | 6 | 66 min | 50 % | 8.3 min | rate | 33 min | 75 % | 55 % |
| j-20260927-0359-8b3e | proof35-replay-base | replay | 6 | 66 min | 75 % | 12 min | rate | 17 min | 25 % | 20 % |
| j-20260927-0435-e0de | proof35-replay-head-3 | replay | 6 | 34 min | 25 % | 21 min | rate | 25 min | 19 % | 71 % |
| j-20260927-0435-e0de | proof35-replay-head-3 | replay | 6 | 34 min | 50 % | 11 min | rate | 17 min | 32 % | 79 % |
| j-20260927-0435-e0de | proof35-replay-head-3 | replay | 6 | 34 min | 75 % | 6.3 min | rate | 8.4 min | 25 % | 38 % |
| j-20260927-0435-e6e1 | proof42-replay-head-3 | replay | 6 | 28 min | 25 % | 26 min | history | 21 min | 23 % | - |
| j-20260927-0435-e6e1 | proof42-replay-head-3 | replay | 6 | 28 min | 50 % | 15 min | rate | 14 min | 4 % | 30 % |
| j-20260927-0435-e6e1 | proof42-replay-head-3 | replay | 6 | 28 min | 75 % | 7.6 min | rate | 7 min | 8 % | 55 % |
| j-20260927-1524-45ef | fix179-after | bench | 15 | 2 h 43 min | 25 % | 86 min | rate | 2 h 02 min | 30 % | 11 % |
| j-20260927-1524-45ef | fix179-after | bench | 15 | 2 h 43 min | 50 % | 81 min | rate | 82 min | 1 % | 47 % |
| j-20260927-1524-45ef | fix179-after | bench | 15 | 2 h 43 min | 75 % | 31 min | rate | 41 min | 25 % | 77 % |
| j-20260927-1526-72cb | fix171-after-tpl | bench | 7 | 2 h 21 min | 25 % | 1 h 42 min | history | 1 h 46 min | 3 % | 42 % |
| j-20260927-1526-72cb | fix171-after-tpl | bench | 7 | 2 h 21 min | 50 % | 65 min | rate | 70 min | 7 % | 64 % |
| j-20260927-1526-72cb | fix171-after-tpl | bench | 7 | 2 h 21 min | 75 % | 40 min | rate | 35 min | 14 % | 53 % |
| j-20261001-1021-dacb | fix174-before-main | bench | 3 | 68 min | 25 % | 52 min | history | 51 min | 1 % | 19 % |
| j-20261001-1021-dacb | fix174-before-main | bench | 3 | 68 min | 50 % | 34 min | history | 34 min | 1 % | 29 % |
| j-20261001-1021-dacb | fix174-before-main | bench | 3 | 68 min | 75 % | 13 min | rate | 17 min | 25 % | 43 % |
| j-20261001-1021-95c3 | issue188-before-main | bench | 5 | 1 h 50 min | 25 % | 45 min | history | 82 min | 45 % | 57 % |
| j-20261001-1021-95c3 | issue188-before-main | bench | 5 | 1 h 50 min | 50 % | 18 min | history | 55 min | 68 % | 78 % |
| j-20261001-1021-95c3 | issue188-before-main | bench | 5 | 1 h 50 min | 75 % | 21 min | rate | 27 min | 25 % | 90 % |
| j-20261001-1021-2e4e | fix179-controls-before-main | bench | 2 | 43 min | 25 % | 58 min | history | 32 min | 80 % | 80 % |
| j-20261001-1021-2e4e | fix179-controls-before-main | bench | 2 | 43 min | 50 % | 47 min | history | 21 min | 121 % | 121 % |
| j-20261001-1021-2e4e | fix179-controls-before-main | bench | 2 | 43 min | 75 % | 37 min | history | 11 min | 241 % | 241 % |
| j-20261001-1105-8316 | issue188-after-r2 | bench | 5 | 64 min | 25 % | 1 h 33 min | history | 48 min | 95 % | 58 % |
| j-20261001-1105-8316 | issue188-after-r2 | bench | 5 | 64 min | 50 % | 8 min | rate | 32 min | 75 % | 69 % |
| j-20261001-1105-8316 | issue188-after-r2 | bench | 5 | 64 min | 75 % | 12 min | rate | 16 min | 25 % | 194 % |
| j-20261001-1134-2276 | fix179-after-r4 | bench | 15 | 1 h 49 min | 25 % | 2 h 01 min | rate | 81 min | 49 % | 44 % |
| j-20261001-1134-2276 | fix179-after-r4 | bench | 15 | 1 h 49 min | 50 % | 63 min | rate | 54 min | 15 % | 26 % |
| j-20261001-1134-2276 | fix179-after-r4 | bench | 15 | 1 h 49 min | 75 % | 31 min | rate | 27 min | 14 % | 49 % |
| j-20261001-1134-2c03 | fix179-controls-after-r4 | bench | 2 | 32 min | 25 % | 35 min | history | 24 min | 45 % | 42 % |
| j-20261001-1134-2c03 | fix179-controls-after-r4 | bench | 2 | 32 min | 50 % | 27 min | history | 16 min | 67 % | 63 % |
| j-20261001-1134-2c03 | fix179-controls-after-r4 | bench | 2 | 32 min | 75 % | 6 min | rate | 8 min | 25 % | 134 % |
| j-20261001-1135-8079 | proof35r2-replay-base | replay | 6 | 23 min | 25 % | 5.7 min | rate | 18 min | 67 % | 67 % |
| j-20261001-1135-8079 | proof35r2-replay-base | replay | 6 | 23 min | 50 % | 2.9 min | rate | 12 min | 75 % | 53 % |
| j-20261001-1135-8079 | proof35r2-replay-base | replay | 6 | 23 min | 75 % | 4.4 min | rate | 5.9 min | 25 % | 21 % |
| j-20261001-1135-a283 | proof35r2-replay-base2 | replay | 6 | 28 min | 25 % | 18 min | rate | 21 min | 12 % | 72 % |
| j-20261001-1135-a283 | proof35r2-replay-base2 | replay | 6 | 28 min | 50 % | 12 min | rate | 14 min | 13 % | 63 % |
| j-20261001-1135-a283 | proof35r2-replay-base2 | replay | 6 | 28 min | 75 % | 5.2 min | rate | 7 min | 25 % | 2 % |
| j-20261001-1135-47dd | proof35r2-replay-head | replay | 6 | 27 min | 25 % | 21 min | rate | 20 min | 5 % | 68 % |
| j-20261001-1135-47dd | proof35r2-replay-head | replay | 6 | 27 min | 50 % | 13 min | rate | 14 min | 8 % | 47 % |
| j-20261001-1135-47dd | proof35r2-replay-head | replay | 6 | 27 min | 75 % | 6.1 min | rate | 6.8 min | 11 % | 12 % |
| j-20261001-1138-40a6 | 392-before | bench | 65 | 14 h 10 min | 25 % | 6 h 23 min | rate | 10 h 38 min | 40 % | 43 % |
| j-20261001-1138-40a6 | 392-before | bench | 65 | 14 h 10 min | 50 % | 2 h 21 min | rate | 7 h 05 min | 67 % | 70 % |
| j-20261001-1138-40a6 | 392-before | bench | 65 | 14 h 10 min | 75 % | 47 min | rate | 3 h 33 min | 78 % | 85 % |
| j-20261002-1447-3045 | proof42r2-replay-base | replay | 6 | 33 min | 25 % | 19 min | history | 25 min | 24 % | - |
| j-20261002-1447-3045 | proof42r2-replay-base | replay | 6 | 33 min | 50 % | 17 min | rate | 16 min | 6 % | 51 % |
| j-20261002-1447-3045 | proof42r2-replay-base | replay | 6 | 33 min | 75 % | 9.7 min | rate | 8.2 min | 19 % | 74 % |
| j-20261002-1447-aa5c | proof42r2-replay-head | replay | 6 | 32 min | 25 % | 21 min | rate | 24 min | 10 % | 68 % |
| j-20261002-1447-aa5c | proof42r2-replay-head | replay | 6 | 32 min | 50 % | 15 min | rate | 16 min | 5 % | 57 % |
| j-20261002-1447-aa5c | proof42r2-replay-head | replay | 6 | 32 min | 75 % | 5.9 min | rate | 7.9 min | 25 % | 17 % |
| j-20261002-1447-7cf3 | proof42r2-replay-base2 | replay | 6 | 34 min | 25 % | 23 min | history | 25 min | 11 % | - |
| j-20261002-1447-7cf3 | proof42r2-replay-base2 | replay | 6 | 34 min | 50 % | 18 min | rate | 17 min | 9 % | 46 % |
| j-20261002-1447-7cf3 | proof42r2-replay-base2 | replay | 6 | 34 min | 75 % | 8.9 min | rate | 8.4 min | 5 % | 26 % |
| j-20261002-1517-6b63 | fix493-replay-a | replay | 6 | 36 min | 25 % | 20 min | rate | 27 min | 25 % | 72 % |
| j-20261002-1517-6b63 | fix493-replay-a | replay | 6 | 36 min | 50 % | 11 min | rate | 18 min | 38 % | 57 % |
| j-20261002-1517-6b63 | fix493-replay-a | replay | 6 | 36 min | 75 % | 6.7 min | rate | 9 min | 25 % | 10 % |
| j-20261002-1517-9111 | fix493-replay-b | replay | 6 | 30 min | 25 % | 24 min | rate | 23 min | 7 % | 67 % |
| j-20261002-1517-9111 | fix493-replay-b | replay | 6 | 30 min | 50 % | 18 min | rate | 15 min | 17 % | 42 % |
| j-20261002-1517-9111 | fix493-replay-b | replay | 6 | 30 min | 75 % | 9.8 min | rate | 7.6 min | 29 % | 34 % |
| j-20261002-1546-3df5 | b464-kick-joint-base | replay | 6 | 11 min | 25 % | нет оценки | - | 8.4 min | - | - |
| j-20261002-1546-3df5 | b464-kick-joint-base | replay | 6 | 11 min | 50 % | 2.9 min | rate | 5.6 min | 48 % | 22 % |
| j-20261002-1546-3df5 | b464-kick-joint-base | replay | 6 | 11 min | 75 % | 2.1 min | rate | 2.8 min | 25 % | 26 % |
| j-20261002-1546-ce26 | b464-kick-joint-head | replay | 6 | 13 min | 25 % | 7.5 min | against | 9.6 min | 23 % | 38 % |
| j-20261002-1546-ce26 | b464-kick-joint-head | replay | 6 | 13 min | 50 % | 2.9 min | rate | 6.4 min | 55 % | 29 % |
| j-20261002-1546-ce26 | b464-kick-joint-head | replay | 6 | 13 min | 75 % | 2.4 min | rate | 3.2 min | 25 % | 52 % |
| j-20261002-1801-b840 | b170-base | bench | 10 | 45 min | 25 % | 21 min | rate | 34 min | 37 % | 310 % |
| j-20261002-1801-b840 | b170-base | bench | 10 | 45 min | 50 % | 11 min | rate | 22 min | 53 % | 91 % |
| j-20261002-1801-b840 | b170-base | bench | 10 | 45 min | 75 % | 13 min | rate | 11 min | 18 % | 39 % |
| j-20261002-1801-ab7c | b170-head | bench | 10 | 43 min | 25 % | 34 min | rate | 33 min | 6 % | 12 % |
| j-20261002-1801-ab7c | b170-head | bench | 10 | 43 min | 50 % | 24 min | rate | 22 min | 8 % | 18 % |
| j-20261002-1801-ab7c | b170-head | bench | 10 | 43 min | 75 % | 13 min | rate | 11 min | 16 % | 37 % |
| j-20261002-1814-50e2 | b34-base | replay | 6 | 28 min | 25 % | 23 min | history | 21 min | 11 % | - |
| j-20261002-1814-50e2 | b34-base | replay | 6 | 28 min | 50 % | 12 min | rate | 14 min | 11 % | 44 % |
| j-20261002-1814-50e2 | b34-base | replay | 6 | 28 min | 75 % | 5.2 min | rate | 6.9 min | 25 % | 3 % |
| j-20261002-1814-5255 | b34-head | replay | 6 | 31 min | 25 % | 19 min | against | 24 min | 20 % | 8 % |
| j-20261002-1814-5255 | b34-head | replay | 6 | 31 min | 50 % | 16 min | rate | 16 min | 1 % | 49 % |
| j-20261002-1814-5255 | b34-head | replay | 6 | 31 min | 75 % | 9.3 min | rate | 7.9 min | 18 % | 19 % |
| j-20261002-2021-87d4 | t510-base | replay | 6 | 30 min | 25 % | 20 min | rate | 23 min | 13 % | 69 % |
| j-20261002-2021-87d4 | t510-base | replay | 6 | 30 min | 50 % | 11 min | rate | 15 min | 26 % | 51 % |
| j-20261002-2021-87d4 | t510-base | replay | 6 | 30 min | 75 % | 5.6 min | rate | 7.5 min | 25 % | 2 % |
| j-20261002-2021-dde3 | t510-head | replay | 6 | 32 min | 25 % | 22 min | history | 24 min | 8 % | - |
| j-20261002-2021-dde3 | t510-head | replay | 6 | 32 min | 50 % | 21 min | rate | 16 min | 33 % | 58 % |
| j-20261002-2021-dde3 | t510-head | replay | 6 | 32 min | 75 % | 11 min | rate | 8 min | 38 % | 27 % |
| j-20261002-2203-80cb | b189-base | bench | 5 | 17 min | 25 % | 2 h 13 min | history | 13 min | 934 % | 591 % |
| j-20261002-2203-80cb | b189-base | bench | 5 | 17 min | 50 % | 8.2 min | rate | 8.6 min | 4 % | 652 % |
| j-20261002-2203-80cb | b189-base | bench | 5 | 17 min | 75 % | 4.2 min | rate | 4.3 min | 3 % | 840 % |
| j-20261002-2203-de0a | b189-head | bench | 5 | 18 min | 25 % | 13 min | history | 13 min | 5 % | 17 % |
| j-20261002-2203-de0a | b189-head | bench | 5 | 18 min | 50 % | 9.4 min | rate | 8.8 min | 6 % | 22 % |
| j-20261002-2203-de0a | b189-head | bench | 5 | 18 min | 75 % | 4.3 min | rate | 4.4 min | 2 % | 45 % |
| j-20261002-2306-3910 | t510-base2 | replay | 6 | 30 min | 25 % | 24 min | history | 22 min | 7 % | - |
| j-20261002-2306-3910 | t510-base2 | replay | 6 | 30 min | 50 % | 13 min | rate | 15 min | 11 % | 39 % |
| j-20261002-2306-3910 | t510-base2 | replay | 6 | 30 min | 75 % | 6.8 min | rate | 7.4 min | 8 % | 47 % |
| j-20261002-2306-06d7 | t510-head2 | replay | 6 | 27 min | 25 % | 22 min | history | 20 min | 10 % | - |
| j-20261002-2306-06d7 | t510-head2 | replay | 6 | 27 min | 50 % | 13 min | rate | 13 min | 4 % | 33 % |
| j-20261002-2306-06d7 | t510-head2 | replay | 6 | 27 min | 75 % | 6.3 min | rate | 6.7 min | 7 % | 39 % |
| j-20261003-0012-4045 | t510-base3 | replay | 6 | 28 min | 25 % | 19 min | rate | 21 min | 10 % | 69 % |
| j-20261003-0012-4045 | t510-base3 | replay | 6 | 28 min | 50 % | 13 min | rate | 14 min | 8 % | 58 % |
| j-20261003-0012-4045 | t510-base3 | replay | 6 | 28 min | 75 % | 5.5 min | rate | 7 min | 20 % | 2 % |
| j-20261003-0012-4a13 | t510-head3 | replay | 6 | 26 min | 25 % | 21 min | history | 19 min | 7 % | - |
| j-20261003-0012-4a13 | t510-head3 | replay | 6 | 26 min | 50 % | 14 min | rate | 13 min | 12 % | 56 % |
| j-20261003-0012-4a13 | t510-head3 | replay | 6 | 26 min | 75 % | 7.8 min | rate | 6.4 min | 22 % | 37 % |
| j-20261003-1251-49d6 | t519-base | replay | 6 | 31 min | 25 % | 17 min | history | 23 min | 24 % | - |
| j-20261003-1251-49d6 | t519-base | replay | 6 | 31 min | 50 % | 14 min | rate | 15 min | 9 % | 51 % |
| j-20261003-1251-49d6 | t519-base | replay | 6 | 31 min | 75 % | 7 min | rate | 7.6 min | 8 % | 45 % |
| j-20261003-1251-95fd | t519-head | replay | 6 | 29 min | 25 % | 21 min | rate | 22 min | 5 % | 67 % |
| j-20261003-1251-95fd | t519-head | replay | 6 | 29 min | 50 % | 14 min | rate | 15 min | 6 % | 51 % |
| j-20261003-1251-95fd | t519-head | replay | 6 | 29 min | 75 % | 6.5 min | rate | 7.3 min | 12 % | 37 % |
| j-20261003-2137-2eb5 | b15-base | replay | 6 | 12 min | 25 % | 26 min | history | 9.2 min | 180 % | - |
| j-20261003-2137-2eb5 | b15-base | replay | 6 | 12 min | 50 % | 23 min | history | 6.2 min | 271 % | - |
| j-20261003-2137-2eb5 | b15-base | replay | 6 | 12 min | 75 % | 2.3 min | rate | 3.1 min | 25 % | 54 % |
| j-20261003-2137-644b | b15-head | replay | 6 | 12 min | 25 % | 8.7 min | against | 9.1 min | 5 % | 51 % |
| j-20261003-2137-644b | b15-head | replay | 6 | 12 min | 50 % | 6.6 min | against | 6.1 min | 8 % | 126 % |
| j-20261003-2137-644b | b15-head | replay | 6 | 12 min | 75 % | 2.3 min | rate | 3 min | 23 % | 49 % |
| j-20261003-2139-436b | b17-head | replay | 6 | 15 min | 25 % | 8 min | against | 11 min | 27 % | 25 % |
| j-20261003-2139-436b | b17-head | replay | 6 | 15 min | 50 % | 6.9 min | against | 7.4 min | 6 % | 87 % |
| j-20261003-2139-436b | b17-head | replay | 6 | 15 min | 75 % | 2.6 min | rate | 3.7 min | 29 % | 117 % |
| j-20261003-2319-c1d9 | b533-jewel-base | replay | 6 | 33 min | 25 % | 4.4 min | rate | 25 min | 82 % | 82 % |
| j-20261003-2319-c1d9 | b533-jewel-base | replay | 6 | 33 min | 50 % | 4.1 min | rate | 16 min | 75 % | 55 % |
| j-20261003-2319-c1d9 | b533-jewel-base | replay | 6 | 33 min | 75 % | 0 s | rate | 8.2 min | 100 % | 100 % |
| j-20261003-2319-b8f0 | b533-cluster-base | replay | 6 | 40 min | 25 % | нет оценки | - | 30 min | - | - |
| j-20261003-2319-b8f0 | b533-cluster-base | replay | 6 | 40 min | 50 % | 7.1 min | rate | 20 min | 64 % | 14 % |
| j-20261003-2319-b8f0 | b533-cluster-base | replay | 6 | 40 min | 75 % | 0 s | rate | 9.9 min | 100 % | 100 % |
| j-20261003-2334-295f | b533-flask-base | replay | 6 | 21 min | 25 % | нет оценки | - | 16 min | - | - |
| j-20261003-2334-295f | b533-flask-base | replay | 6 | 21 min | 50 % | 9.4 min | rate | 11 min | 12 % | 12 % |
| j-20261003-2334-295f | b533-flask-base | replay | 6 | 21 min | 75 % | 7.1 min | rate | 5.3 min | 33 % | 146 % |
| j-20261003-2337-012c | smoke-14-11 | bench | 13 | 4 h 07 min | 25 % | 29 min | history | 3 h 06 min | 84 % | 96 % |
| j-20261003-2337-012c | smoke-14-11 | bench | 13 | 4 h 07 min | 50 % | 48 min | rate | 2 h 04 min | 61 % | 100 % |
| j-20261003-2337-012c | smoke-14-11 | bench | 13 | 4 h 07 min | 75 % | 57 min | rate | 62 min | 7 % | 25 % |
| j-20261003-2341-9f71 | b534-a | replay | 6 | 13 min | 25 % | 10 min | history | 9.5 min | 9 % | - |
| j-20261003-2341-9f71 | b534-a | replay | 6 | 13 min | 50 % | 7.4 min | history | 6.3 min | 16 % | - |
| j-20261003-2341-9f71 | b534-a | replay | 6 | 13 min | 75 % | 1.8 min | rate | 3.2 min | 44 % | 114 % |
| j-20261003-2341-0f64 | b534-b | replay | 6 | 15 min | 25 % | 8.4 min | history | 11 min | 23 % | - |
| j-20261003-2341-0f64 | b534-b | replay | 6 | 15 min | 50 % | 7.4 min | history | 7.3 min | 2 % | - |
| j-20261003-2341-0f64 | b534-b | replay | 6 | 15 min | 75 % | 3 min | rate | 3.6 min | 18 % | 38 % |
| j-20261004-0007-a91f | b533-jewel-head | replay | 6 | 15 min | 25 % | 14 min | against | 11 min | 25 % | 87 % |
| j-20261004-0007-a91f | b533-jewel-head | replay | 6 | 15 min | 50 % | 6.5 min | rate | 7.6 min | 14 % | 19 % |
| j-20261004-0007-a91f | b533-jewel-head | replay | 6 | 15 min | 75 % | 3.1 min | rate | 3.8 min | 17 % | 85 % |
| j-20261004-0007-94bc | b533-cluster-head | replay | 6 | 26 min | 25 % | 20 min | against | 19 min | 3 % | 89 % |
| j-20261004-0007-94bc | b533-cluster-head | replay | 6 | 26 min | 50 % | 13 min | rate | 13 min | 3 % | 30 % |
| j-20261004-0007-94bc | b533-cluster-head | replay | 6 | 26 min | 75 % | 5.4 min | rate | 6.5 min | 17 % | 110 % |
| j-20261004-0007-0650 | b533-flask-head | replay | 6 | 18 min | 25 % | 14 min | against | 14 min | 4 % | 86 % |
| j-20261004-0007-0650 | b533-flask-head | replay | 6 | 18 min | 50 % | 11 min | against | 9.1 min | 18 % | 178 % |
| j-20261004-0007-0650 | b533-flask-head | replay | 6 | 18 min | 75 % | 3.5 min | rate | 4.6 min | 23 % | 115 % |
| j-20261004-0453-6977 | b547-loop-base | replay | 6 | 23 min | 25 % | 16 min | history | 17 min | 6 % | - |
| j-20261004-0453-6977 | b547-loop-base | replay | 6 | 23 min | 50 % | 9.6 min | rate | 12 min | 17 % | 28 % |
| j-20261004-0453-6977 | b547-loop-base | replay | 6 | 23 min | 75 % | 3.6 min | rate | 5.8 min | 38 % | 16 % |
| j-20261004-0453-8850 | b547-loop-head | replay | 6 | 32 min | 25 % | 18 min | history | 24 min | 25 % | - |
| j-20261004-0453-8850 | b547-loop-head | replay | 6 | 32 min | 50 % | 14 min | rate | 16 min | 10 % | 28 % |
| j-20261004-0453-8850 | b547-loop-head | replay | 6 | 32 min | 75 % | 7.4 min | rate | 7.9 min | 6 % | 7 % |
| j-20261004-0555-6afd | b534-e | replay | 6 | 16 min | 25 % | 13 min | history | 12 min | 15 % | - |
| j-20261004-0555-6afd | b534-e | replay | 6 | 16 min | 50 % | 11 min | history | 7.8 min | 35 % | - |
| j-20261004-0555-6afd | b534-e | replay | 6 | 16 min | 75 % | 4.5 min | rate | 3.9 min | 16 % | 48 % |
| j-20261004-0555-53f6 | b534-f | replay | 6 | 14 min | 25 % | 10 min | history | 10 min | 3 % | - |
| j-20261004-0555-53f6 | b534-f | replay | 6 | 14 min | 50 % | 8.1 min | history | 7 min | 17 % | - |
| j-20261004-0555-53f6 | b534-f | replay | 6 | 14 min | 75 % | 4.4 min | rate | 3.5 min | 27 % | 76 % |
| j-20261004-0608-5a65 | b550-loop-base | replay | 6 | 25 min | 25 % | 21 min | history | 19 min | 7 % | - |
| j-20261004-0608-5a65 | b550-loop-base | replay | 6 | 25 min | 50 % | 11 min | rate | 13 min | 17 % | 22 % |
| j-20261004-0608-5a65 | b550-loop-base | replay | 6 | 25 min | 75 % | 3.7 min | rate | 6.4 min | 42 % | 11 % |
| j-20261004-0608-9e12 | b550-loop-head | replay | 6 | 26 min | 25 % | 20 min | history | 19 min | 6 % | - |
| j-20261004-0608-9e12 | b550-loop-head | replay | 6 | 26 min | 50 % | 11 min | rate | 13 min | 15 % | 21 % |
| j-20261004-0608-9e12 | b550-loop-head | replay | 6 | 26 min | 75 % | 4.9 min | rate | 6.4 min | 24 % | 5 % |
| j-20261004-0759-e056 | b548-555-loop-base | replay | 6 | 28 min | 25 % | 18 min | history | 21 min | 15 % | - |
| j-20261004-0759-e056 | b548-555-loop-base | replay | 6 | 28 min | 50 % | 12 min | rate | 14 min | 13 % | 13 % |
| j-20261004-0759-e056 | b548-555-loop-base | replay | 6 | 28 min | 75 % | 3.8 min | rate | 7.1 min | 47 % | 1 % |
| j-20261004-0759-0143 | b548-loop-head | replay | 6 | 28 min | 25 % | 18 min | history | 21 min | 15 % | - |
| j-20261004-0759-0143 | b548-loop-head | replay | 6 | 28 min | 50 % | 12 min | rate | 14 min | 15 % | 15 % |
| j-20261004-0759-0143 | b548-loop-head | replay | 6 | 28 min | 75 % | 3.7 min | rate | 7.1 min | 47 % | 3 % |
| j-20261004-0759-9f26 | b555-loop-head | replay | 6 | 29 min | 25 % | 18 min | history | 22 min | 16 % | - |
| j-20261004-0759-9f26 | b555-loop-head | replay | 6 | 29 min | 50 % | 13 min | rate | 14 min | 13 % | 13 % |
| j-20261004-0759-9f26 | b555-loop-head | replay | 6 | 29 min | 75 % | 4.6 min | rate | 7.2 min | 36 % | 12 % |
| j-20261004-0842-edf8 | b557-loop-base | replay | 6 | 26 min | 25 % | 21 min | history | 19 min | 10 % | - |
| j-20261004-0842-edf8 | b557-loop-base | replay | 6 | 26 min | 50 % | 8.4 min | rate | 13 min | 35 % | 37 % |
| j-20261004-0842-edf8 | b557-loop-base | replay | 6 | 26 min | 75 % | 4.3 min | rate | 6.4 min | 34 % | 11 % |
| j-20261004-0849-c6e7 | b557-loop-head | replay | 6 | 25 min | 25 % | 21 min | history | 19 min | 15 % | - |
| j-20261004-0849-c6e7 | b557-loop-head | replay | 6 | 25 min | 50 % | 11 min | rate | 12 min | 10 % | 13 % |
| j-20261004-0849-c6e7 | b557-loop-head | replay | 6 | 25 min | 75 % | 4.9 min | rate | 6.2 min | 21 % | 9 % |
| j-20261004-0910-dfb2 | b559-loop-base | replay | 6 | 21 min | 25 % | 18 min | history | 16 min | 13 % | - |
| j-20261004-0910-dfb2 | b559-loop-base | replay | 6 | 21 min | 50 % | 7.9 min | rate | 11 min | 26 % | 26 % |
| j-20261004-0910-dfb2 | b559-loop-base | replay | 6 | 21 min | 75 % | 3.5 min | rate | 5.3 min | 35 % | 8 % |
| j-20261004-0910-47d1 | b559-loop-head | replay | 6 | 21 min | 25 % | 16 min | history | 16 min | 1 % | - |
| j-20261004-0910-47d1 | b559-loop-head | replay | 6 | 21 min | 50 % | 10 min | rate | 10 min | 3 % | 18 % |
| j-20261004-0910-47d1 | b559-loop-head | replay | 6 | 21 min | 75 % | 4.6 min | rate | 5.2 min | 12 % | 0 % |
| j-20261005-1220-cca4 | gate-20261005 | bench | 61 | 23 h 58 min | 25 % | 34 h 00 min | history | 17 h 58 min | 89 % | 89 % |
| j-20261005-1220-cca4 | gate-20261005 | bench | 61 | 23 h 58 min | 50 % | 11 h 15 min | rate | 11 h 59 min | 6 % | 6 % |
| j-20261005-1220-cca4 | gate-20261005 | bench | 61 | 23 h 58 min | 75 % | 11 h 15 min | rate | 5 h 59 min | 88 % | 88 % |
| j-20261006-0148-4ff5 | b575-base | replay | 6 | 17 min | 25 % | нет оценки | - | 13 min | - | - |
| j-20261006-0148-4ff5 | b575-base | replay | 6 | 17 min | 50 % | 7.5 min | rate | 8.3 min | 10 % | 4 % |
| j-20261006-0148-4ff5 | b575-base | replay | 6 | 17 min | 75 % | 3.6 min | rate | 4.2 min | 14 % | 8 % |
| j-20261006-1042-d19b | P1-#580-06.10 | bench | 5 | 3 h 07 min | 25 % | 2 h 39 min | history | 2 h 20 min | 13 % | 4 % |
| j-20261006-1042-d19b | P1-#580-06.10 | bench | 5 | 3 h 07 min | 50 % | 4 h 54 min | rate | 1 h 34 min | 214 % | 167 % |
| j-20261006-1042-d19b | P1-#580-06.10 | bench | 5 | 3 h 07 min | 75 % | 52 min | rate | 47 min | 12 % | 11 % |
| j-20261006-1042-6ea8 | P1-#580-06.10-2 | bench | 5 | 3 h 12 min | 25 % | 43 min | history | 2 h 24 min | 70 % | 81 % |
| j-20261006-1042-6ea8 | P1-#580-06.10-2 | bench | 5 | 3 h 12 min | 50 % | 82 min | rate | 1 h 36 min | 15 % | 40 % |
| j-20261006-1042-6ea8 | P1-#580-06.10-2 | bench | 5 | 3 h 12 min | 75 % | 34 min | rate | 48 min | 30 % | 30 % |
| j-20261006-1248-8afe | P1-#575-06.10 | replay | 6 | 13 min | 25 % | 18 min | against | 9.9 min | 87 % | 71 % |
| j-20261006-1248-8afe | P1-#575-06.10 | replay | 6 | 13 min | 50 % | 5.8 min | rate | 6.6 min | 12 % | 5 % |
| j-20261006-1248-8afe | P1-#575-06.10 | replay | 6 | 13 min | 75 % | 78 s | rate | 3.3 min | 60 % | 1 % |
| j-20261006-1622-1116 | P1-#51-06.10-3 | replay | 6 | 89 min | 25 % | 38 min | history | 67 min | 44 % | - |
| j-20261006-1622-1116 | P1-#51-06.10-3 | replay | 6 | 89 min | 50 % | 86 min | rate | 45 min | 91 % | 256 % |
| j-20261006-1622-1116 | P1-#51-06.10-3 | replay | 6 | 89 min | 75 % | 39 min | rate | 22 min | 74 % | 63 % |
| j-20261006-1701-f0b5 | P1-#589-06.10 | replay | 6 | 28 min | 25 % | 23 min | rate | 21 min | 7 % | 65 % |
| j-20261006-1701-f0b5 | P1-#589-06.10 | replay | 6 | 28 min | 50 % | 14 min | rate | 14 min | 1 % | 27 % |
| j-20261006-1701-f0b5 | P1-#589-06.10 | replay | 6 | 28 min | 75 % | 5.8 min | rate | 7.1 min | 18 % | 31 % |
| j-20261006-1705-0520 | P1-#51-06.10-6 | replay | 6 | 88 min | 25 % | 66 min | history | 66 min | 0 % | - |
| j-20261006-1705-0520 | P1-#51-06.10-6 | replay | 6 | 88 min | 50 % | 41 min | rate | 44 min | 7 % | 251 % |
| j-20261006-1705-0520 | P1-#51-06.10-6 | replay | 6 | 88 min | 75 % | 22 min | rate | 22 min | 1 % | 86 % |
| j-20261006-1801-f4e4 | P1-#589-06.10-3 | replay | 6 | 17 min | 25 % | 8 min | against | 13 min | 37 % | 30 % |
| j-20261006-1801-f4e4 | P1-#589-06.10-3 | replay | 6 | 17 min | 50 % | 7.2 min | rate | 8.5 min | 16 % | 3 % |
| j-20261006-1801-f4e4 | P1-#589-06.10-3 | replay | 6 | 17 min | 75 % | 2.6 min | rate | 4.3 min | 38 % | 2 % |
| j-20261006-1902-a488 | P1-#589-06.10-5 | replay | 6 | 18 min | 25 % | 12 min | against | 14 min | 10 % | 1 % |
| j-20261006-1902-a488 | P1-#589-06.10-5 | replay | 6 | 18 min | 50 % | 10 min | rate | 9 min | 14 % | 36 % |
| j-20261006-1902-a488 | P1-#589-06.10-5 | replay | 6 | 18 min | 75 % | 2.9 min | rate | 4.5 min | 36 % | 41 % |
| j-20261006-2227-cbe8 | P1-#596 | replay | 6 | 14 min | 25 % | 6.2 min | against | 10 min | 40 % | 14 % |
| j-20261006-2227-cbe8 | P1-#596 | replay | 6 | 14 min | 50 % | 3.3 min | rate | 6.9 min | 52 % | 64 % |
| j-20261006-2227-cbe8 | P1-#596 | replay | 6 | 14 min | 75 % | 81 s | rate | 3.5 min | 61 % | 30 % |
| j-20261006-2238-155d | P1-#12 | replay | 6 | 57 min | 25 % | нет оценки | - | 43 min | - | - |
| j-20261006-2238-155d | P1-#12 | replay | 6 | 57 min | 50 % | 43 min | rate | 28 min | 52 % | 54 % |
| j-20261006-2238-155d | P1-#12 | replay | 6 | 57 min | 75 % | 30 min | rate | 14 min | 110 % | 108 % |
| j-20261006-2238-864d | P1-#12-2 | replay | 6 | 56 min | 25 % | 41 min | against | 42 min | 2 % | 3 % |
| j-20261006-2238-864d | P1-#12-2 | replay | 6 | 56 min | 50 % | 34 min | rate | 28 min | 21 % | 85 % |
| j-20261006-2238-864d | P1-#12-2 | replay | 6 | 56 min | 75 % | 16 min | rate | 14 min | 14 % | 141 % |
| j-20261006-2240-9479 | P1-#569 | replay | 6 | 56 min | 25 % | 41 min | against | 42 min | 2 % | 3 % |
| j-20261006-2240-9479 | P1-#569 | replay | 6 | 56 min | 50 % | 34 min | rate | 28 min | 21 % | 85 % |
| j-20261006-2240-9479 | P1-#569 | replay | 6 | 56 min | 75 % | 17 min | rate | 14 min | 19 % | 155 % |
| j-20261006-2257-e0ba | P1-#553 | replay | 6 | 31 min | 25 % | 28 min | against | 24 min | 18 % | 39 % |
| j-20261006-2257-e0ba | P1-#553 | replay | 6 | 31 min | 50 % | 29 min | rate | 16 min | 83 % | 51 % |
| j-20261006-2257-e0ba | P1-#553 | replay | 6 | 31 min | 75 % | 23 min | rate | 7.9 min | 193 % | 70 % |
| j-20261007-0135-1e44 | P1-#616 | replay | 6 | 24 min | 25 % | 9.5 min | against | 18 min | 47 % | 29 % |
| j-20261007-0135-1e44 | P1-#616 | replay | 6 | 24 min | 50 % | 9.3 min | rate | 12 min | 22 % | 24 % |
| j-20261007-0135-1e44 | P1-#616 | replay | 6 | 24 min | 75 % | 3.9 min | rate | 5.9 min | 35 % | 22 % |
| j-20261007-0151-4ec6 | P1-#553-2 | replay | 6 | 22 min | 25 % | 11 min | rate | 16 min | 33 % | 12 % |
| j-20261007-0151-4ec6 | P1-#553-2 | replay | 6 | 22 min | 50 % | 9.9 min | rate | 11 min | 10 % | 21 % |
| j-20261007-0151-4ec6 | P1-#553-2 | replay | 6 | 22 min | 75 % | 3.3 min | rate | 5.5 min | 39 % | 19 % |
| j-20261007-0151-e422 | P1-#553-3 | replay | 6 | 1 h 46 min | 25 % | 53 min | rate | 79 min | 33 % | 63 % |
| j-20261007-0151-e422 | P1-#553-3 | replay | 6 | 1 h 46 min | 50 % | 51 min | rate | 53 min | 3 % | 89 % |
| j-20261007-0151-e422 | P1-#553-3 | replay | 6 | 1 h 46 min | 75 % | 34 min | rate | 26 min | 28 % | 137 % |
| j-20261007-0213-70ea | P1-#616-2 | replay | 6 | 22 min | 25 % | 9 min | against | 17 min | 46 % | 23 % |
| j-20261007-0213-70ea | P1-#616-2 | replay | 6 | 22 min | 50 % | 8.2 min | rate | 11 min | 25 % | 70 % |
| j-20261007-0213-70ea | P1-#616-2 | replay | 6 | 22 min | 75 % | 3.3 min | rate | 5.5 min | 40 % | 20 % |
| j-20261007-0222-3b52 | P1-#617-2 | bench | 4 | 34 min | 25 % | 82 min | history | 25 min | 225 % | 179 % |
| j-20261007-0222-3b52 | P1-#617-2 | bench | 4 | 34 min | 50 % | 74 min | history | 17 min | 337 % | 269 % |
| j-20261007-0222-3b52 | P1-#617-2 | bench | 4 | 34 min | 75 % | 6.3 min | rate | 8.4 min | 25 % | 680 % |
| j-20261007-0225-e86b | P1-#617-3 | bench | 6 | 25 min | 25 % | 40 min | history | 19 min | 114 % | 38 % |
| j-20261007-0225-e86b | P1-#617-3 | bench | 6 | 25 min | 50 % | 11 min | rate | 13 min | 14 % | 41 % |
| j-20261007-0225-e86b | P1-#617-3 | bench | 6 | 25 min | 75 % | 6.8 min | rate | 6.3 min | 9 % | 145 % |
| j-20261007-0251-9763 | P1-#616-3 | replay | 6 | 16 min | 25 % | 8.6 min | against | 12 min | 27 % | 7 % |
| j-20261007-0251-9763 | P1-#616-3 | replay | 6 | 16 min | 50 % | 9.8 min | rate | 7.9 min | 24 % | 30 % |
| j-20261007-0251-9763 | P1-#616-3 | replay | 6 | 16 min | 75 % | 5.2 min | rate | 3.9 min | 31 % | 62 % |
| j-20261009-1054-64e2 | P1-#600 | bench | 8 | 4 h 13 min | 25 % | 84 min | history | 3 h 09 min | 55 % | 70 % |
| j-20261009-1054-64e2 | P1-#600 | bench | 8 | 4 h 13 min | 50 % | 2 h 01 min | rate | 2 h 06 min | 4 % | 77 % |
| j-20261009-1054-64e2 | P1-#600 | bench | 8 | 4 h 13 min | 75 % | 54 min | rate | 63 min | 14 % | 83 % |
| j-20261010-0046-f553 | P1-#553-8 | replay | 6 | 35 min | 25 % | 27 min | against | 26 min | 4 % | 12 % |
| j-20261010-0046-f553 | P1-#553-8 | replay | 6 | 35 min | 50 % | 26 min | rate | 17 min | 48 % | 43 % |
| j-20261010-0046-f553 | P1-#553-8 | replay | 6 | 35 min | 75 % | 20 min | rate | 8.6 min | 126 % | 28 % |
| j-20261010-0046-1fcc | P1-#553-9 | replay | 6 | 16 min | 25 % | 6.4 min | against | 12 min | 47 % | 1 % |
| j-20261010-0046-1fcc | P1-#553-9 | replay | 6 | 16 min | 50 % | 3.4 min | rate | 8.1 min | 58 % | 14 % |
| j-20261010-0046-1fcc | P1-#553-9 | replay | 6 | 16 min | 75 % | 0 s | rate | 4.1 min | 100 % | 100 % |
| j-20261010-0046-517a | P1-#604-2 | bench | 8 | 3 h 21 min | 25 % | 2 h 43 min | history | 2 h 31 min | 8 % | 23 % |
| j-20261010-0046-517a | P1-#604-2 | bench | 8 | 3 h 21 min | 50 % | 4 h 04 min | rate | 1 h 41 min | 142 % | 23 % |
| j-20261010-0046-517a | P1-#604-2 | bench | 8 | 3 h 21 min | 75 % | 2 h 36 min | rate | 50 min | 211 % | 33 % |
| j-20261010-0422-ab64 | P1-#604-3 | bench | 8 | 7 h 27 min | 25 % | 6 h 58 min | history | 5 h 35 min | 25 % | 5 % |
| j-20261010-0422-ab64 | P1-#604-3 | bench | 8 | 7 h 27 min | 50 % | 4 h 30 min | rate | 3 h 43 min | 21 % | 0 % |
| j-20261010-0422-ab64 | P1-#604-3 | bench | 8 | 7 h 27 min | 75 % | 71 min | rate | 1 h 52 min | 37 % | 53 % |
| j-20261010-0426-7b99 | P1-#718 | replay | 6 | 47 min | 25 % | 38 min | history | 35 min | 10 % | - |
| j-20261010-0426-7b99 | P1-#718 | replay | 6 | 47 min | 50 % | 25 min | rate | 23 min | 6 % | 42 % |
| j-20261010-0426-7b99 | P1-#718 | replay | 6 | 47 min | 75 % | 13 min | rate | 12 min | 13 % | 1 % |
| j-20261010-0426-08e7 | P1-#718-2 | replay | 6 | 10 min | 25 % | 9.8 min | against | 7.7 min | 27 % | 54 % |
| j-20261010-0426-08e7 | P1-#718-2 | replay | 6 | 10 min | 50 % | 4.8 min | rate | 5.1 min | 6 % | 45 % |
| j-20261010-0426-08e7 | P1-#718-2 | replay | 6 | 10 min | 75 % | 57 s | rate | 2.6 min | 63 % | 53 % |
| j-20261010-0430-ebd4 | P1-#601 | replay | 6 | 45 min | 25 % | 43 min | rate | 34 min | 29 % | 45 % |
| j-20261010-0430-ebd4 | P1-#601 | replay | 6 | 45 min | 50 % | 22 min | rate | 22 min | 4 % | 44 % |
| j-20261010-0430-ebd4 | P1-#601 | replay | 6 | 45 min | 75 % | 16 min | rate | 11 min | 45 % | 28 % |
| j-20261010-0430-6a6c | P1-#601-2 | replay | 6 | 1 h 41 min | 25 % | 38 min | history | 76 min | 50 % | - |
| j-20261010-0430-6a6c | P1-#601-2 | replay | 6 | 1 h 41 min | 50 % | 41 min | rate | 50 min | 19 % | 50 % |
| j-20261010-0430-6a6c | P1-#601-2 | replay | 6 | 1 h 41 min | 75 % | 14 min | rate | 25 min | 45 % | 68 % |
| j-20261011-0037-98fe | P1-#786 | replay | 6 | 39 min | 25 % | 4.1 min | rate | 29 min | 86 % | 88 % |
| j-20261011-0037-98fe | P1-#786 | replay | 6 | 39 min | 50 % | 3.5 min | rate | 19 min | 82 % | 99 % |
| j-20261011-0037-98fe | P1-#786 | replay | 6 | 39 min | 75 % | 5.9 min | rate | 9.7 min | 39 % | 97 % |
| j-20261011-0126-3c1e | P1-#795 | replay | 7 | 55 min | 25 % | 9.9 min | rate | 41 min | 76 % | 68 % |
| j-20261011-0126-3c1e | P1-#795 | replay | 7 | 55 min | 50 % | 4.6 min | rate | 27 min | 83 % | 98 % |
| j-20261011-0126-3c1e | P1-#795 | replay | 7 | 55 min | 75 % | 5.9 min | rate | 14 min | 57 % | 68 % |
| j-20261011-0126-120e | P1-#795-2 | replay | 7 | 44 min | 25 % | 49 min | rate | 33 min | 50 % | 41 % |
| j-20261011-0126-120e | P1-#795-2 | replay | 7 | 44 min | 50 % | 18 min | rate | 22 min | 19 % | 92 % |
| j-20261011-0126-120e | P1-#795-2 | replay | 7 | 44 min | 75 % | 5.4 min | rate | 11 min | 50 % | 84 % |
| j-20261011-0419-27c2 | P1-#813 | replay | 7 | 41 min | 25 % | 41 min | rate | 31 min | 35 % | 53 % |
| j-20261011-0419-27c2 | P1-#813 | replay | 7 | 41 min | 50 % | 26 min | rate | 20 min | 27 % | 67 % |
| j-20261011-0419-27c2 | P1-#813 | replay | 7 | 41 min | 75 % | 14 min | rate | 10 min | 39 % | 37 % |
| j-20261011-0419-2070 | P1-#813-2 | replay | 7 | 1 h 41 min | 25 % | 33 min | rate | 76 min | 57 % | 51 % |
| j-20261011-0419-2070 | P1-#813-2 | replay | 7 | 1 h 41 min | 50 % | 10 min | rate | 50 min | 80 % | 72 % |
| j-20261011-0419-2070 | P1-#813-2 | replay | 7 | 1 h 41 min | 75 % | 8.9 min | rate | 25 min | 65 % | 96 % |
| j-20261011-0419-e12c | P1-#813-3 | replay | 7 | 32 min | 25 % | 12 min | rate | 24 min | 48 % | 79 % |
| j-20261011-0419-e12c | P1-#813-3 | replay | 7 | 32 min | 50 % | 4.9 min | rate | 16 min | 69 % | 99 % |
| j-20261011-0419-e12c | P1-#813-3 | replay | 7 | 32 min | 75 % | 4.1 min | rate | 7.9 min | 49 % | 97 % |
| j-20261011-0419-7609 | P1-#813-4 | replay | 7 | 2 h 53 min | 25 % | 2 h 15 min | rate | 2 h 10 min | 4 % | 57 % |
| j-20261011-0419-7609 | P1-#813-4 | replay | 7 | 2 h 53 min | 50 % | 2 h 03 min | rate | 86 min | 42 % | 36 % |
| j-20261011-0419-7609 | P1-#813-4 | replay | 7 | 2 h 53 min | 75 % | 1 h 43 min | rate | 43 min | 139 % | 53 % |
| j-20261011-0430-e070 | P1-#816 | bench | 2 | 3 h 25 min | 25 % | 13 min | history | 2 h 34 min | 92 % | 93 % |
| j-20261011-0430-e070 | P1-#816 | bench | 2 | 3 h 25 min | 50 % | 51 min | rate | 1 h 43 min | 51 % | 51 % |
| j-20261011-0430-e070 | P1-#816 | bench | 2 | 3 h 25 min | 75 % | 19 min | rate | 51 min | 62 % | 93 % |
| j-20261011-0940-488f | P1-#813-5 | replay | 7 | 42 min | 25 % | 30 min | rate | 31 min | 5 % | 52 % |
| j-20261011-0940-488f | P1-#813-5 | replay | 7 | 42 min | 50 % | 13 min | rate | 21 min | 38 % | 79 % |
| j-20261011-0940-488f | P1-#813-5 | replay | 7 | 42 min | 75 % | 4.7 min | rate | 10 min | 55 % | 78 % |
| j-20261011-0940-9f4c | P1-#813-6 | replay | 7 | 2 h 12 min | 25 % | 1 h 37 min | rate | 1 h 39 min | 2 % | 40 % |
| j-20261011-0940-9f4c | P1-#813-6 | replay | 7 | 2 h 12 min | 50 % | 41 min | rate | 66 min | 39 % | 61 % |
| j-20261011-0940-9f4c | P1-#813-6 | replay | 7 | 2 h 12 min | 75 % | 10 min | rate | 33 min | 70 % | 95 % |
| j-20261011-0940-d42e | P1-#813-7 | replay | 7 | 1 h 37 min | 25 % | 50 min | rate | 73 min | 31 % | 54 % |
| j-20261011-0940-d42e | P1-#813-7 | replay | 7 | 1 h 37 min | 50 % | 30 min | rate | 48 min | 39 % | 74 % |
| j-20261011-0940-d42e | P1-#813-7 | replay | 7 | 1 h 37 min | 75 % | 9.4 min | rate | 24 min | 61 % | 96 % |
| j-20261011-1442-eb50 | P1-#854 | replay | 7 | 60 min | 25 % | 23 min | rate | 45 min | 48 % | 73 % |
| j-20261011-1442-eb50 | P1-#854 | replay | 7 | 60 min | 50 % | 15 min | rate | 30 min | 49 % | 98 % |
| j-20261011-1442-eb50 | P1-#854 | replay | 7 | 60 min | 75 % | 7.4 min | rate | 15 min | 50 % | 97 % |
| j-20261011-1442-3911 | P1-#854-2 | replay | 7 | 37 min | 25 % | 49 min | rate | 28 min | 75 % | 66 % |
| j-20261011-1442-3911 | P1-#854-2 | replay | 7 | 37 min | 50 % | 25 min | rate | 19 min | 36 % | 81 % |
| j-20261011-1442-3911 | P1-#854-2 | replay | 7 | 37 min | 75 % | 11 min | rate | 9.3 min | 17 % | 38 % |
| j-20261011-2304-00a8 | P1-#880-2 | replay | 7 | 65 min | 25 % | 19 min | rate | 49 min | 61 % | 75 % |
| j-20261011-2304-00a8 | P1-#880-2 | replay | 7 | 65 min | 50 % | 5.1 min | rate | 32 min | 84 % | 80 % |
| j-20261011-2304-00a8 | P1-#880-2 | replay | 7 | 65 min | 75 % | 8.4 min | rate | 16 min | 48 % | 89 % |
| j-20261013-1830-e4b6 | P1-#956-8 | replay | 6 | 4 h 30 min | 25 % | нет оценки | - | 3 h 23 min | - | - |
| j-20261013-1830-e4b6 | P1-#956-8 | replay | 6 | 4 h 30 min | 50 % | 2 h 27 min | rate | 2 h 15 min | 9 % | 51 % |
| j-20261013-1830-e4b6 | P1-#956-8 | replay | 6 | 4 h 30 min | 75 % | 2 h 13 min | rate | 68 min | 97 % | 104 % |
