package internal

import "testing"

func TestDecodeDocumentChange(t *testing.T) {
	change, err := decodeDocumentChange([]byte(`{"document_id":"42","operation":"update","timestamp":1,"source":"manual.pdf","file_path":"/data/uploads/manual.pdf"}`))
	if err != nil {
		t.Fatal(err)
	}
	if change.Operation != "UPDATE" {
		t.Fatalf("operation=%s", change.Operation)
	}
}

func TestDecodeDocumentChangeRejectsMissingPath(t *testing.T) {
	_, err := decodeDocumentChange([]byte(`{"document_id":"42","operation":"INSERT","source":"manual.pdf"}`))
	if err == nil {
		t.Fatal("expected validation error")
	}
}

func TestDecodeCanalFlatMessage(t *testing.T) {
	changes, err := decodeDocumentChanges([]byte(`{"data":[{"id":"42","source":"manual.pdf","file_path":"/app/data/uploads/manual.pdf"}],"database":"rag_cdc","table":"document_records","es":123,"isDdl":false,"type":"UPDATE"}`))
	if err != nil {
		t.Fatal(err)
	}
	if len(changes) != 1 || changes[0].DocumentID != "42" || changes[0].Operation != "UPDATE" {
		t.Fatalf("unexpected Canal change: %+v", changes)
	}
}

func TestDecodeCanalDDLIgnored(t *testing.T) {
	_, err := decodeDocumentChanges([]byte(`{"data":null,"isDdl":true,"type":"CREATE"}`))
	if err != ErrMessageIgnored {
		t.Fatalf("error=%v, want ErrMessageIgnored", err)
	}
}
