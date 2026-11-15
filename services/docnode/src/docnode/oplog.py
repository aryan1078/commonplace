"""Where batches of operations are ordered before they reach the state machine.

`LocalLog` applies each batch immediately on this one node (single-node mode
and tests). `docnode.raft.RaftLog` first replicates the batch to a majority of
nodes and only then applies it. The gRPC server only sees the `Log`
protocol, so it is the same code in both cases.
"""

from typing import Protocol

from .statemachine import Batch, Result, StateMachine


class NotLeader(Exception):
    """This node cannot accept writes; `leader` is where to send them
    (an address, or "" if no leader is known right now)."""

    def __init__(self, leader: str):
        super().__init__(f"not the leader; leader is {leader or 'unknown'}")
        self.leader = leader


class Log(Protocol):
    async def propose(self, batch: Batch) -> Result:
        """Adds the batch to the log and waits until it has been applied.

        Returns the state machine's result, or raises its ApplyError (for
        example StaleError), or NotLeader.
        """
        ...


class LocalLog:
    """Applies batches directly, in the order propose is called."""

    def __init__(self, sm: StateMachine):
        self._sm = sm

    async def propose(self, batch: Batch) -> Result:
        return self._sm.apply(batch)
