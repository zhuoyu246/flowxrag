package internal

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

// DocumentChange is the stable Kafka contract emitted by Canal or a document
// producer. file_path must be reachable through the shared RAG data volume.
type DocumentChange struct {
	DocumentID string `json:"document_id"`
	Operation  string `json:"operation"`
	Timestamp  int64  `json:"timestamp"`
	Source     string `json:"source"`
	FilePath   string `json:"file_path"`
}

// ErrMessageIgnored is used for Canal DDL/control events. They are committed
// without being sent to the DLQ because they do not represent a document.
var ErrMessageIgnored = errors.New("non-document Canal event")

type canalEnvelope struct {
	Data  []canalDocument `json:"data"`
	Type  string          `json:"type"`
	Es    int64           `json:"es"`
	Ts    int64           `json:"ts"`
	IsDDL bool            `json:"isDdl"`
}

type canalDocument struct {
	ID         string `json:"id"`
	DocumentID string `json:"document_id"`
	Source     string `json:"source"`
	FilePath   string `json:"file_path"`
}

// decodeDocumentChanges accepts both the application producer's compact event
// and Canal's flat JSON envelope. Canal can batch several changed rows in one
// Kafka record, so callers must process every returned change.
func decodeDocumentChanges(value []byte) ([]DocumentChange, error) {
	var change DocumentChange
	if err := json.Unmarshal(value, &change); err != nil {
		return nil, fmt.Errorf("invalid JSON: %w", err)
	}
	if change.DocumentID != "" || change.Operation != "" {
		if err := validateDocumentChange(&change); err != nil {
			return nil, err
		}
		return []DocumentChange{change}, nil
	}

	var envelope canalEnvelope
	if err := json.Unmarshal(value, &envelope); err != nil {
		return nil, fmt.Errorf("invalid Canal JSON: %w", err)
	}
	if envelope.IsDDL || len(envelope.Data) == 0 {
		return nil, ErrMessageIgnored
	}
	changes := make([]DocumentChange, 0, len(envelope.Data))
	for _, row := range envelope.Data {
		documentID := row.DocumentID
		if documentID == "" {
			documentID = row.ID
		}
		change := DocumentChange{
			DocumentID: documentID,
			Operation:  envelope.Type,
			Timestamp:  envelope.Es,
			Source:     row.Source,
			FilePath:   row.FilePath,
		}
		if change.Timestamp == 0 {
			change.Timestamp = envelope.Ts
		}
		if err := validateDocumentChange(&change); err != nil {
			return nil, fmt.Errorf("invalid Canal row: %w", err)
		}
		changes = append(changes, change)
	}
	return changes, nil
}

// decodeDocumentChange is retained for focused callers and legacy tests.
func decodeDocumentChange(value []byte) (DocumentChange, error) {
	changes, err := decodeDocumentChanges(value)
	if err != nil {
		return DocumentChange{}, err
	}
	return changes[0], nil
}

func validateDocumentChange(change *DocumentChange) error {
	change.Operation = strings.ToUpper(strings.TrimSpace(change.Operation))
	if change.DocumentID == "" || change.Source == "" {
		return fmt.Errorf("document_id and source are required")
	}
	if change.Operation != "INSERT" && change.Operation != "UPDATE" && change.Operation != "DELETE" {
		return fmt.Errorf("unsupported operation %q", change.Operation)
	}
	if change.Operation != "DELETE" && change.FilePath == "" {
		return fmt.Errorf("file_path is required for %s", change.Operation)
	}
	return nil
}
