window.BENCHMARK_DATA = {
  "lastUpdate": 1775037372184,
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
      }
    ]
  }
}