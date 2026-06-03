window.BENCHMARK_DATA = {
  "lastUpdate": 1780482334230,
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
      }
    ]
  }
}