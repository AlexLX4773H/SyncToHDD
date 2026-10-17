from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import String, Integer, BigInteger, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class SyncRun(Base):
    __tablename__ = "sync_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sync_pair_id: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    sync_pair_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(Text, default="", nullable=False)
    destination: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default="running",
        nullable=False,
    )  # running | completed | failed | cancelled
    files_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_modified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_unchanged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bytes_transferred: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    error_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    changes: Mapped[List["FileChange"]] = relationship(
        "FileChange",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="FileChange.change_id",
    )

class FileChange(Base):
    __tablename__ = "file_changes"

    change_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sync_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # added | modified | deleted | unchanged | error
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_mtime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped["SyncRun"] = relationship("SyncRun", back_populates="changes")

    __table_args__ = (
        Index("idx_file_changes_run_id", "run_id"),
        Index("idx_file_changes_action", "action"),
    )
