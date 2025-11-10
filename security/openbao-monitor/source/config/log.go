package baoConfig

import (
	"context"
	"io"
	"log"
	"log/slog"
)

const (
	LevelFatal = slog.Level(12)
)

type BaoHandler struct {
	slog.Handler
	level slog.Leveler
	l     *log.Logger
}

func (h *BaoHandler) Enabled(_ context.Context, lvl slog.Level) bool {
	return lvl >= h.level.Level()
}

func (h *BaoHandler) Handle(_ context.Context, r slog.Record) error {
	levelStr := ""
	if r.Level.Level() == LevelFatal {
		levelStr = "FATAL"
	} else {
		levelStr = r.Level.String()
	}
	timeStr := r.Time.Format("2006-01-02T15:04:05")
	msgStr := r.Message

	h.l.Println(timeStr, levelStr, msgStr)

	return nil
}

func NewBaoHandler(out io.Writer, opts *slog.HandlerOptions) *BaoHandler {
	newHandler := &BaoHandler{
		level: slog.LevelInfo,
		l:     log.New(out, "", 0),
	}
	if opts.Level.Level() != slog.LevelInfo {
		newHandler.level = opts.Level.Level()
	}

	return newHandler
}
