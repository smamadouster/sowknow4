"""
Validate ONNX/INT8 against the FP32 baseline stored in sowknow.document_chunks.

Reports:
  - cosine(FP32_stored, INT8_recomputed) distribution
  - top-k retrieval agreement (Jaccard) using each vector as a query

Usage:
    DATABASE_URL=postgresql://... python scripts/validate_onnx_embeddings.py --sample 500
"""

import argparse
import os
import statistics
import sys

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.embedding_service_onnx import EmbeddingServiceONNX

DATABASE_URL = os.environ.get("DATABASE_URL")


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def parse_pgvector(s) -> np.ndarray:
    if isinstance(s, (list, tuple)):
        return np.asarray(s, dtype=np.float32)
    return np.asarray([float(x) for x in s.strip("[]").split(",")], dtype=np.float32)


def fetch_sample(conn, n: int) -> list[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, content, embedding
            FROM sowknow.document_chunks
            WHERE embedding IS NOT NULL
              AND length(content) BETWEEN 50 AND 4000
            ORDER BY random()
            LIMIT %s
            """,
            (n,),
        )
        return cur.fetchall()


def topk_neighbours(conn, vector: list[float], k: int, exclude_id: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text
            FROM sowknow.document_chunks
            WHERE embedding IS NOT NULL AND id::text != %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (exclude_id, vector, k),
        )
        return [row[0] for row in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=500)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument(
        "--retrieval-n",
        type=int,
        default=100,
        help="how many of the sampled chunks to use for top-k agreement",
    )
    ap.add_argument("--database-url", default=DATABASE_URL)
    args = ap.parse_args()

    if not args.database_url:
        print("ERROR: set DATABASE_URL or pass --database-url", file=sys.stderr)
        sys.exit(1)

    svc = EmbeddingServiceONNX()
    conn = psycopg2.connect(args.database_url)

    print(f"Sampling {args.sample} chunks...")
    rows = fetch_sample(conn, args.sample)
    print(f"  got {len(rows)}")

    print("Re-embedding with ONNX/INT8...")
    new_embs = svc.encode([r["content"] for r in rows], batch_size=16)

    cosines: list[float] = []
    paired: list[tuple[str, np.ndarray, np.ndarray]] = []
    for row, new in zip(rows, new_embs):
        fp32 = parse_pgvector(row["embedding"])
        int8 = np.asarray(new, dtype=np.float32)
        cosines.append(cosine(fp32, int8))
        paired.append((str(row["id"]), fp32, int8))

    p_sorted = sorted(cosines)
    print("\n=== Cosine similarity FP32 vs INT8 ===")
    print(f"  mean: {statistics.mean(cosines):.4f}")
    print(f"  p50:  {statistics.median(cosines):.4f}")
    print(f"  p5:   {p_sorted[int(0.05 * len(p_sorted))]:.4f}")
    print(f"  p1:   {p_sorted[int(0.01 * len(p_sorted))]:.4f}")
    print(f"  min:  {min(cosines):.4f}")
    print(f"  < 0.98: {sum(1 for c in cosines if c < 0.98)} / {len(cosines)}")
    print(f"  < 0.95: {sum(1 for c in cosines if c < 0.95)} / {len(cosines)}")

    print(f"\n=== Top-{args.k} retrieval agreement ===")
    overlaps: list[float] = []
    for cid, fp32, int8 in paired[: args.retrieval_n]:
        nb_a = set(topk_neighbours(conn, fp32.tolist(), args.k, cid))
        nb_b = set(topk_neighbours(conn, int8.tolist(), args.k, cid))
        if nb_a or nb_b:
            overlaps.append(len(nb_a & nb_b) / len(nb_a | nb_b))

    if overlaps:
        print(f"  mean Jaccard: {statistics.mean(overlaps):.3f}")
        print(f"  p50:          {statistics.median(overlaps):.3f}")
        print(f"  perfect:      {sum(1 for o in overlaps if o == 1.0)} / {len(overlaps)}")
        print(f"  < 0.7:        {sum(1 for o in overlaps if o < 0.7)} / {len(overlaps)}")

    conn.close()

    mean_cos = statistics.mean(cosines)
    mean_jacc = statistics.mean(overlaps) if overlaps else 0.0
    print()
    if mean_cos >= 0.99 and mean_jacc >= 0.85:
        print("VERDICT: PASS — safe to swap.")
    elif mean_cos >= 0.97 and mean_jacc >= 0.75:
        print("VERDICT: ACCEPTABLE — minor drop. Run real-query A/B before switching.")
    else:
        print("VERDICT: FAIL — investigate export config.")


if __name__ == "__main__":
    main()
