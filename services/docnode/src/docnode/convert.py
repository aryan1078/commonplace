"""Conversions between protobuf messages and the state machine's own types.

The state machine uses plain frozen dataclasses so its rules can be read and
tested without protobuf; the gRPC server and the Raft log convert at the edge.
"""

from collections.abc import Iterable

from collab.v1 import common_pb2, document_pb2

from .statemachine import Batch, Committed, OpId, Operation
from .text import Change


def operation_from_proto(p: common_pb2.Operation) -> Operation:
    return Operation(
        op_id=OpId(p.op_id.client_id, p.op_id.seq),
        doc_id=p.doc_id,
        base_revision=p.base_revision,
        changes=tuple(Change(c.range.start, c.range.end, c.insert) for c in p.changes),
        user_id=p.user_id,
    )


def operation_to_proto(op: Operation) -> common_pb2.Operation:
    return common_pb2.Operation(
        op_id=common_pb2.OpId(client_id=op.op_id.client_id, seq=op.op_id.seq),
        doc_id=op.doc_id,
        base_revision=op.base_revision,
        changes=[
            common_pb2.TextChange(
                range=common_pb2.TextRange(start=c.start, end=c.end), insert=c.insert
            )
            for c in op.changes
        ],
        user_id=op.user_id,
    )


def batch_from_proto(doc_id: str, ops: Iterable[common_pb2.Operation]) -> Batch:
    return Batch(doc_id=doc_id, ops=tuple(operation_from_proto(p) for p in ops))


def committed_to_proto(c: Committed) -> document_pb2.SubscribeResponse:
    return document_pb2.SubscribeResponse(revision=c.revision, operation=operation_to_proto(c.op))
