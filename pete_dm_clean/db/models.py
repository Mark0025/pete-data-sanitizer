from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pete_dm_clean.db.base import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    runs: Mapped[list["Run"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Run(Base):
    __tablename__ = "runs"

    # run_id is already unique and stable in your app (e.g. 2026-01-15_00-20-16)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)

    company_id: Mapped[Optional[str]] = mapped_column(ForeignKey("companies.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    app_version: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    overall_status: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    overall_reasons: Mapped[str] = mapped_column(Text, default="", nullable=False)  # JSON string (small)

    # Stored as text for portability; typically relative to uploads dir.
    run_json_path: Mapped[str] = mapped_column(Text, default="", nullable=False)

    company: Mapped[Optional[Company]] = relationship(back_populates="runs")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Artifact(Base):
    """
    Small metadata pointers to files on disk (inputs/outputs/reports/diagrams/logs).
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "role", "key", name="uq_artifact_run_role_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)

    # role: input | output | diagnostic
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # key: e.g. contacts, desired_outcome, out_xlsx, out_csv, report_md, debug_md...
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)

    run: Mapped[Run] = relationship(back_populates="artifacts")

