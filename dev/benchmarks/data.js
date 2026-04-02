window.BENCHMARK_DATA = {
  "lastUpdate": 1775117603252,
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
      }
    ]
  }
}