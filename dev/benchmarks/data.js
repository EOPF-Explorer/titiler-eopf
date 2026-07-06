window.BENCHMARK_DATA = {
  "lastUpdate": 1783351674800,
  "repoUrl": "https://github.com/EOPF-Explorer/titiler-eopf",
  "entries": {
    "titiler-eopf Benchmarks": [
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "abc30140cdbc78c1b8d5cb41bd377e12ee9ba5c6",
          "message": "Merge pull request #94 from EOPF-Explorer/feat/add-benchmark\n\nfeat: add pytest benchmark",
          "timestamp": "2026-04-01T11:47:30+02:00",
          "tree_id": "226b8936171edd1b21c1a080256430eea661c143",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/abc30140cdbc78c1b8d5cb41bd377e12ee9ba5c6"
        },
        "date": 1775037371878,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 36.33220200669118,
            "unit": "iter/sec",
            "range": "stddev: 0.011692564123072211",
            "extra": "mean: 27.52379280000241 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 31.976418307308556,
            "unit": "iter/sec",
            "range": "stddev: 0.0008658133446658439",
            "extra": "mean: 31.27304597999455 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.37385508734123,
            "unit": "iter/sec",
            "range": "stddev: 0.019370928618134147",
            "extra": "mean: 421.2557056800051 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 3.3575489998774932,
            "unit": "iter/sec",
            "range": "stddev: 0.02779707718672072",
            "extra": "mean: 297.8363085800049 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "d1835603a1b1c89e2d00d4d4b403de9416b1d594",
          "message": "Merge pull request #95 from EOPF-Explorer/feat/update-dependencies-01042026\n\nfeat: update dependencies and set python >=3.12",
          "timestamp": "2026-04-02T10:10:14+02:00",
          "tree_id": "302be8478cb2f43193da4659ffc9912b4d31a891",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/d1835603a1b1c89e2d00d4d4b403de9416b1d594"
        },
        "date": 1775117602415,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 34.55731736753834,
            "unit": "iter/sec",
            "range": "stddev: 0.010231859637400916",
            "extra": "mean: 28.93743137999934 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 31.28420816713128,
            "unit": "iter/sec",
            "range": "stddev: 0.0023350810205622647",
            "extra": "mean: 31.965009139999548 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.4544692459708237,
            "unit": "iter/sec",
            "range": "stddev: 0.019802002669543475",
            "extra": "mean: 407.4200569599995 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 3.3132968347101324,
            "unit": "iter/sec",
            "range": "stddev: 0.03190682630314654",
            "extra": "mean: 301.8141898799979 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "afe2d7c012b1a3d67547a95e67d595f1e7008f7d",
          "message": "Merge pull request #96 from EOPF-Explorer/perf/avoid-writing-crs\n\nperf: avoid writing CRS to dataarray",
          "timestamp": "2026-04-02T14:51:48+02:00",
          "tree_id": "6b11a894337ad4aab1e28771f78d050d45cec807",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/afe2d7c012b1a3d67547a95e67d595f1e7008f7d"
        },
        "date": 1775134486339,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 36.74287955824022,
            "unit": "iter/sec",
            "range": "stddev: 0.01001390157127091",
            "extra": "mean: 27.216157579999276 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 35.20773351780841,
            "unit": "iter/sec",
            "range": "stddev: 0.0004193299646183949",
            "extra": "mean: 28.402850739999792 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.615371244270951,
            "unit": "iter/sec",
            "range": "stddev: 0.01792940969660511",
            "extra": "mean: 382.3548959600018 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 3.4109211394504184,
            "unit": "iter/sec",
            "range": "stddev: 0.034165152885246665",
            "extra": "mean: 293.17593668000313 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "41898282+github-actions[bot]@users.noreply.github.com",
            "name": "github-actions[bot]",
            "username": "github-actions[bot]"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "06f0ddcff1f1cc4189be4e105578b884f34c5dae",
          "message": "chore: release 0.8.0 (#72)\n\nCo-authored-by: github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>",
          "timestamp": "2026-04-17T10:17:28+02:00",
          "tree_id": "1504f37edcdf7c9cb170901f78697445bb2a8404",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/06f0ddcff1f1cc4189be4e105578b884f34c5dae"
        },
        "date": 1776414019719,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 39.255209774399525,
            "unit": "iter/sec",
            "range": "stddev: 0.009509744778415022",
            "extra": "mean: 25.47432572000048 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 38.522334083232025,
            "unit": "iter/sec",
            "range": "stddev: 0.0005569045315923269",
            "extra": "mean: 25.95896701999891 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.8756083535308203,
            "unit": "iter/sec",
            "range": "stddev: 0.01613302919809611",
            "extra": "mean: 347.75250209999854 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 3.668027489386194,
            "unit": "iter/sec",
            "range": "stddev: 0.025573319687378485",
            "extra": "mean: 272.62609205999695 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "49f51a0f9672cff32c29bdd222ba4ecce4bafaa3",
          "message": "Merge pull request #102 from EOPF-Explorer/feat/add-scale-offset-support\n\nfeat: add support for scale/offset codec",
          "timestamp": "2026-05-20T09:23:35+02:00",
          "tree_id": "43c7aaf95e0c0b66b886463f31a238304866cf65",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/49f51a0f9672cff32c29bdd222ba4ecce4bafaa3"
        },
        "date": 1779262004213,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 37.28802505382324,
            "unit": "iter/sec",
            "range": "stddev: 0.011852257702054",
            "extra": "mean: 26.81826131999628 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 35.747272786934715,
            "unit": "iter/sec",
            "range": "stddev: 0.000721935725609733",
            "extra": "mean: 27.974162000002707 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.8038318887021916,
            "unit": "iter/sec",
            "range": "stddev: 0.01940222568069906",
            "extra": "mean: 356.6547638000043 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 3.4411367336124172,
            "unit": "iter/sec",
            "range": "stddev: 0.036162465041944994",
            "extra": "mean: 290.60164632000124 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "c09b2a205eb22cfa8a3af244924ff2adaa8a3f79",
          "message": "Merge pull request #100 from EOPF-Explorer/dependabot/github_actions/all-02ecabffd2\n\nchore(deps): bump the all group across 1 directory with 5 updates",
          "timestamp": "2026-05-20T09:23:57+02:00",
          "tree_id": "94ae1266deeeafc2f534e1256ac8df254f84a211",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/c09b2a205eb22cfa8a3af244924ff2adaa8a3f79"
        },
        "date": 1779262023733,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 36.66268387710716,
            "unit": "iter/sec",
            "range": "stddev: 0.013117434698568044",
            "extra": "mean: 27.275690000000736 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 36.35137614161458,
            "unit": "iter/sec",
            "range": "stddev: 0.0003685946931459037",
            "extra": "mean: 27.509274919999882 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.7640058923847097,
            "unit": "iter/sec",
            "range": "stddev: 0.025457608186172397",
            "extra": "mean: 361.7937294400002 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 3.404262022213264,
            "unit": "iter/sec",
            "range": "stddev: 0.03642087180240672",
            "extra": "mean: 293.74942160000217 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "beb1c07effd1c7a97dbe6c0907314f7a4a9f2e63",
          "message": "Merge pull request #105 from EOPF-Explorer/dependabot/github_actions/all-ba4e4f20eb\n\nchore(deps): bump the all group with 7 updates",
          "timestamp": "2026-05-27T17:13:52+02:00",
          "tree_id": "ddda2865817cf19c93dfc3e070a56b5584ff3fb3",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/beb1c07effd1c7a97dbe6c0907314f7a4a9f2e63"
        },
        "date": 1779895034874,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 35.16615843878092,
            "unit": "iter/sec",
            "range": "stddev: 0.012693220410780527",
            "extra": "mean: 28.43642991999971 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 33.930394082091695,
            "unit": "iter/sec",
            "range": "stddev: 0.0011101966087096154",
            "extra": "mean: 29.472100960000205 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.729943709707831,
            "unit": "iter/sec",
            "range": "stddev: 0.019744359298869422",
            "extra": "mean: 366.30791925999955 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 3.3375163671969434,
            "unit": "iter/sec",
            "range": "stddev: 0.03239929615473248",
            "extra": "mean: 299.6239988000008 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "94ce5d714a60eafa6f20251fe54439c2d6500953",
          "message": "Merge pull request #107 from EOPF-Explorer/fix/chunk-viewer\n\nfix: chunk viewer and remove comment",
          "timestamp": "2026-06-02T14:30:41+02:00",
          "tree_id": "26729f329cb77d4c2aa825828bece64d37dc7c31",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/94ce5d714a60eafa6f20251fe54439c2d6500953"
        },
        "date": 1780403651119,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 31.805053484338657,
            "unit": "iter/sec",
            "range": "stddev: 0.01328052897118944",
            "extra": "mean: 31.441544359999796 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 31.06388149180925,
            "unit": "iter/sec",
            "range": "stddev: 0.001990107182066014",
            "extra": "mean: 32.19172723999975 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.4194130917771743,
            "unit": "iter/sec",
            "range": "stddev: 0.020652709803695338",
            "extra": "mean: 413.3233813600026 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 3.1653901085288343,
            "unit": "iter/sec",
            "range": "stddev: 0.03742510326635078",
            "extra": "mean: 315.91682721999973 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "4972778c598c93739e10b45b7f15fe3a3f255a39",
          "message": "feat: use experimental xarray-GeoZarr Reader (#99)\n\n* feat: use experimental xarray-GeoZarr Reader\n\n* dep: update rio-tiler\n\n* chore: update rio-tiler dep\n\n* chore: lint and type\n\n* remove v0 in tests\n\n* chore: remove comment\n\n* chore: update rio-tiler version",
          "timestamp": "2026-06-03T12:06:26+02:00",
          "tree_id": "b57ccf533d597d19f8bffcf0bf3763da0c76568c",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/4972778c598c93739e10b45b7f15fe3a3f255a39"
        },
        "date": 1780481379207,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 58.880323413491695,
            "unit": "iter/sec",
            "range": "stddev: 0.009213117614040651",
            "extra": "mean: 16.983602365384805 msec\nrounds: 52"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 61.293490024654695,
            "unit": "iter/sec",
            "range": "stddev: 0.0003999332179389762",
            "extra": "mean: 16.31494632786875 msec\nrounds: 61"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.6388704971050343,
            "unit": "iter/sec",
            "range": "stddev: 0.02053289860619349",
            "extra": "mean: 378.95000952000004 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 2.6022756053179785,
            "unit": "iter/sec",
            "range": "stddev: 0.03194068408421469",
            "extra": "mean: 384.2790509800008 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "41898282+github-actions[bot]@users.noreply.github.com",
            "name": "github-actions[bot]",
            "username": "github-actions[bot]"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "30ea69166f3fe57871e9094015f55419e63db259",
          "message": "chore: release 0.9.0 (#104)\n\nCo-authored-by: github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>",
          "timestamp": "2026-06-03T12:22:44+02:00",
          "tree_id": "8bc83f18cdb0d08a286f6dad1868f0fe1e8b59a1",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/30ea69166f3fe57871e9094015f55419e63db259"
        },
        "date": 1780482333399,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 64.53729552400962,
            "unit": "iter/sec",
            "range": "stddev: 0.0092957673928468",
            "extra": "mean: 15.494916418181374 msec\nrounds: 55"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 69.22894095087236,
            "unit": "iter/sec",
            "range": "stddev: 0.00027287008878124286",
            "extra": "mean: 14.444825910447486 msec\nrounds: 67"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.9625498783503694,
            "unit": "iter/sec",
            "range": "stddev: 0.015718549912774417",
            "extra": "mean: 337.54705948000037 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 2.6736736470398745,
            "unit": "iter/sec",
            "range": "stddev: 0.031840381177416256",
            "extra": "mean: 374.01722573999933 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "emmanuel.mathot@gmail.com",
            "name": "Emmanuel Mathot",
            "username": "emmanuelmathot"
          },
          "committer": {
            "email": "emmanuel.mathot@gmail.com",
            "name": "Emmanuel Mathot",
            "username": "emmanuelmathot"
          },
          "distinct": true,
          "id": "3e5b9641455f77126e723e7168763aae9054d44f",
          "message": "fix: removed legacy cahce",
          "timestamp": "2026-06-08T21:52:54+02:00",
          "tree_id": "57a7a4817b1355c96f409e81f4a5c43fc293247b",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/3e5b9641455f77126e723e7168763aae9054d44f"
        },
        "date": 1780948555482,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 63.79420499821126,
            "unit": "iter/sec",
            "range": "stddev: 0.009968084118280603",
            "extra": "mean: 15.675405000000225 msec\nrounds: 55"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 62.854533051413185,
            "unit": "iter/sec",
            "range": "stddev: 0.0008829354309386394",
            "extra": "mean: 15.909751476190733 msec\nrounds: 63"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 3.0407984034914155,
            "unit": "iter/sec",
            "range": "stddev: 0.017785927314156184",
            "extra": "mean: 328.8609987599999 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 2.6094212457257107,
            "unit": "iter/sec",
            "range": "stddev: 0.03531183980599273",
            "extra": "mean: 383.2267410399996 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "emmanuel.mathot@gmail.com",
            "name": "Emmanuel Mathot",
            "username": "emmanuelmathot"
          },
          "committer": {
            "email": "emmanuel.mathot@gmail.com",
            "name": "Emmanuel Mathot",
            "username": "emmanuelmathot"
          },
          "distinct": true,
          "id": "48057748e5e8adc32eaceb6bc0976520967c37bb",
          "message": "Revert \"chore: release 0.9.0 (#104)\"\n\nThis reverts commit 30ea69166f3fe57871e9094015f55419e63db259.",
          "timestamp": "2026-06-08T21:53:27+02:00",
          "tree_id": "1b54a9825330f6beb98a9a335b8fda9e109e66e9",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/48057748e5e8adc32eaceb6bc0976520967c37bb"
        },
        "date": 1780948590071,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 61.87893982317563,
            "unit": "iter/sec",
            "range": "stddev: 0.013206603172117677",
            "extra": "mean: 16.160587153845647 msec\nrounds: 52"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 66.07695407972449,
            "unit": "iter/sec",
            "range": "stddev: 0.0003605500818587676",
            "extra": "mean: 15.133869499999351 msec\nrounds: 66"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.9557430074397946,
            "unit": "iter/sec",
            "range": "stddev: 0.021556148921027925",
            "extra": "mean: 338.32440691999807 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 2.555234053389277,
            "unit": "iter/sec",
            "range": "stddev: 0.04751722852459352",
            "extra": "mean: 391.3535821399978 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "emmanuel.mathot@gmail.com",
            "name": "Emmanuel Mathot",
            "username": "emmanuelmathot"
          },
          "committer": {
            "email": "emmanuel.mathot@gmail.com",
            "name": "Emmanuel Mathot",
            "username": "emmanuelmathot"
          },
          "distinct": true,
          "id": "1876047cc033d9a5cf2497eb55009c472521a7b6",
          "message": "Reapply \"chore: release 0.9.0 (#104)\"\n\nThis reverts commit 48057748e5e8adc32eaceb6bc0976520967c37bb.",
          "timestamp": "2026-06-08T21:57:46+02:00",
          "tree_id": "8bc83f18cdb0d08a286f6dad1868f0fe1e8b59a1",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/1876047cc033d9a5cf2497eb55009c472521a7b6"
        },
        "date": 1780948852708,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 53.04689785210768,
            "unit": "iter/sec",
            "range": "stddev: 0.011937910587250864",
            "extra": "mean: 18.851243719999502 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 57.390734473189575,
            "unit": "iter/sec",
            "range": "stddev: 0.0008748834234533563",
            "extra": "mean: 17.424415442307257 msec\nrounds: 52"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.5164233858929883,
            "unit": "iter/sec",
            "range": "stddev: 0.020343272058182173",
            "extra": "mean: 397.3894081600008 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 2.5015939304732218,
            "unit": "iter/sec",
            "range": "stddev: 0.03873860177702756",
            "extra": "mean: 399.7451336200004 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "emmanuel.mathot@gmail.com",
            "name": "Emmanuel Mathot",
            "username": "emmanuelmathot"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "b0beec2a9c44ff030e2eef5cfc4622bd9ac19565",
          "message": "fix: removed legacy cahce (#111)",
          "timestamp": "2026-06-09T13:55:49+02:00",
          "tree_id": "57a7a4817b1355c96f409e81f4a5c43fc293247b",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/b0beec2a9c44ff030e2eef5cfc4622bd9ac19565"
        },
        "date": 1781006329633,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 62.436828671412,
            "unit": "iter/sec",
            "range": "stddev: 0.011309730615021312",
            "extra": "mean: 16.016188222222613 msec\nrounds: 54"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 62.916061103325056,
            "unit": "iter/sec",
            "range": "stddev: 0.0009284596298863638",
            "extra": "mean: 15.894192714285333 msec\nrounds: 56"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.9126445325059804,
            "unit": "iter/sec",
            "range": "stddev: 0.021037328812234267",
            "extra": "mean: 343.33060174000025 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 2.495020955766594,
            "unit": "iter/sec",
            "range": "stddev: 0.04516457690082897",
            "extra": "mean: 400.79823685999884 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "41898282+github-actions[bot]@users.noreply.github.com",
            "name": "github-actions[bot]",
            "username": "github-actions[bot]"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "20b01048a1e24d237be1fac5774c15c949a90ce5",
          "message": "chore: release 0.9.1 (#110)\n\nCo-authored-by: Emmanuel Mathot <emmanuel.mathot@gmail.com>",
          "timestamp": "2026-06-09T16:23:41+02:00",
          "tree_id": "db79288ea63cd603462e19eb1b9f2ae3406d11a2",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/20b01048a1e24d237be1fac5774c15c949a90ce5"
        },
        "date": 1781015212896,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 59.2976815374153,
            "unit": "iter/sec",
            "range": "stddev: 0.013791816719013805",
            "extra": "mean: 16.86406574545458 msec\nrounds: 55"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 56.644768779682245,
            "unit": "iter/sec",
            "range": "stddev: 0.0010602712532525374",
            "extra": "mean: 17.653880870967335 msec\nrounds: 62"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.91416091292337,
            "unit": "iter/sec",
            "range": "stddev: 0.028861254369572268",
            "extra": "mean: 343.1519500399996 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 2.494830939319218,
            "unit": "iter/sec",
            "range": "stddev: 0.047541833179820046",
            "extra": "mean: 400.82876327999884 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "8e3814ad022c5595a2c049687dbbe52d3307a2f3",
          "message": "Merge pull request #109 from EOPF-Explorer/dependabot/github_actions/all-3dabcd880e\n\nchore(deps): bump the all group with 3 updates",
          "timestamp": "2026-06-11T11:56:41+02:00",
          "tree_id": "6c0fbcc1a9f4b298524ab93354e2aec1103e2820",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/8e3814ad022c5595a2c049687dbbe52d3307a2f3"
        },
        "date": 1781171984631,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 62.85004406157201,
            "unit": "iter/sec",
            "range": "stddev: 0.0113546230423037",
            "extra": "mean: 15.910887811316961 msec\nrounds: 53"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 61.82911399781294,
            "unit": "iter/sec",
            "range": "stddev: 0.0010957020653404525",
            "extra": "mean: 16.173610380950514 msec\nrounds: 63"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.9921938704962296,
            "unit": "iter/sec",
            "range": "stddev: 0.019440379047430022",
            "extra": "mean: 334.2029438200001 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 2.606678200433968,
            "unit": "iter/sec",
            "range": "stddev: 0.0406166923087925",
            "extra": "mean: 383.6300160999991 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "a6dbbbf8b65c4f2560df70ed1c9c200112ca933d",
          "message": "Merge pull request #116 from EOPF-Explorer/fix/chunck-viewer\n\nfix: chunck viewer",
          "timestamp": "2026-06-11T13:45:13+02:00",
          "tree_id": "2d4e59ab0b2beb56669846b7029cc65481bafc1b",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/a6dbbbf8b65c4f2560df70ed1c9c200112ca933d"
        },
        "date": 1781178506629,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 47.86413707255043,
            "unit": "iter/sec",
            "range": "stddev: 0.013647602747499226",
            "extra": "mean: 20.892468999999778 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 51.008686133458056,
            "unit": "iter/sec",
            "range": "stddev: 0.0015147889918555796",
            "extra": "mean: 19.604504169811804 msec\nrounds: 53"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.051151968444377,
            "unit": "iter/sec",
            "range": "stddev: 0.03270780715480465",
            "extra": "mean: 487.53091696000183 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 2.2897348787620424,
            "unit": "iter/sec",
            "range": "stddev: 0.045016606423535124",
            "extra": "mean: 436.73178466000195 msec\nrounds: 50"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "vincent.sarago@gmail.com",
            "name": "Vincent Sarago",
            "username": "vincentsarago"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "ef3dbc42ca0f98a961b6f95d72fa77885540ec31",
          "message": "Merge pull request #129 from EOPF-Explorer/dependabot/github_actions/all-c9f307b2bc\n\nchore(deps): bump the all group across 1 directory with 9 updates",
          "timestamp": "2026-07-06T17:24:48+02:00",
          "tree_id": "94fc0eedeb0828f9e0569643c813232ef970ac3e",
          "url": "https://github.com/EOPF-Explorer/titiler-eopf/commit/ef3dbc42ca0f98a961b6f95d72fa77885540ec31"
        },
        "date": 1783351673912,
        "tool": "pytest",
        "benches": [
          {
            "name": "GeoZarrReader-Open",
            "value": 56.833627635496505,
            "unit": "iter/sec",
            "range": "stddev: 0.009476317341262858",
            "extra": "mean: 17.595216803923165 msec\nrounds: 51"
          },
          {
            "name": "GeoZarrReader-Info",
            "value": 59.38871373075612,
            "unit": "iter/sec",
            "range": "stddev: 0.0003643468957781155",
            "extra": "mean: 16.838216172412597 msec\nrounds: 58"
          },
          {
            "name": "GeoZarrReader-Preview",
            "value": 2.529504780435348,
            "unit": "iter/sec",
            "range": "stddev: 0.01898407897968183",
            "extra": "mean: 395.33429932000047 msec\nrounds: 50"
          },
          {
            "name": "GeoZarrReader-Tile",
            "value": 2.4511206520091378,
            "unit": "iter/sec",
            "range": "stddev: 0.0385850729867486",
            "extra": "mean: 407.9766531199999 msec\nrounds: 50"
          }
        ]
      }
    ]
  }
}