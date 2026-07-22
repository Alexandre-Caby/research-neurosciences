"""LanceDB data plane: vector search over paper chunk embeddings."""
import argparse

import lancedb
import numpy as np
import pyarrow as pa

from core import config


class LanceStore:
    def __init__(self, lance_dir=None, dim=None):
        self.lance_dir = lance_dir or config.LANCE_DIR
        self.dim = dim
        self.table_name = "chunks"

    def _schema(self, dim) -> pa.Schema:
        return pa.schema([
            pa.field("chunk_id", pa.string()),
            pa.field("paper_id", pa.string()),
            pa.field("doi", pa.string()),
            pa.field("title", pa.string()),
            pa.field("year", pa.int64()),
            pa.field("source", pa.string()),
            pa.field("query_block", pa.string()),
            pa.field("section", pa.string()),
            pa.field("section_index", pa.int64()),
            pa.field("chunk_index", pa.int64()),
            pa.field("word_count", pa.int64()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
            pa.field("extraction_quality", pa.float64()),
        ])

    def open_table(self):
        db = lancedb.connect(self.lance_dir)
        if self.table_name in db.table_names():
            return db.open_table(self.table_name)
        if self.dim is None:
            raise RuntimeError(
                "cannot open table before dim is known: run upsert() first or pass dim"
            )
        return db.create_table(self.table_name, schema=self._schema(self.dim))

    def upsert(self, rows: list[dict]) -> None:
        if not rows:
            return
        if self.dim is None:
            self.dim = len(rows[0]["vector"])

        table = self.open_table()
        data = [self._to_arrow_row(row) for row in rows]
        (
            table.merge_insert("chunk_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(data)
        )

    def _to_arrow_row(self, row: dict) -> dict:
        out = dict(row)
        if isinstance(out["vector"], np.ndarray):
            out["vector"] = out["vector"].tolist()
        return out

    def search(self, vector, k=10) -> list[dict]:
        try:
            table = self.open_table()
        except RuntimeError:
            return []
        return table.search(vector, vector_column_name="vector").limit(k).to_list()

    def export_parquet(self, out_path) -> None:
        table = self.open_table()
        table.to_pandas().to_parquet(out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", required=True)
    args = parser.parse_args()
    LanceStore().export_parquet(args.export)
