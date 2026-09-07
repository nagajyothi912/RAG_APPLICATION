import { useEffect, useState } from 'react';
import Button from '../atoms/Button';
import TextArea from '../atoms/TextArea';
import RetrievalControls from './RetrievalControls';
import GoldenQuestions from './GoldenQuestions';
import type { AskOptions, GoldenQuestion, RetrievalMode } from '../../services/api';

type ChatInputProps = {
  onSend: (text: string, options: AskOptions) => void;
  disabled: boolean;
  productAreas: string[];
  documents: string[];
  goldenQuestions: GoldenQuestion[];
  defaultTopK: number;
  hybridAvailable: boolean;
  rerankerAvailable: boolean;
};

export default function ChatInput({
  onSend,
  disabled,
  productAreas,
  documents,
  goldenQuestions,
  defaultTopK,
  hybridAvailable,
  rerankerAvailable,
}: ChatInputProps) {
  const [value, setValue] = useState('');
  const [mode, setMode] = useState<RetrievalMode>('week3');
  const [topK, setTopK] = useState(defaultTopK);
  const [productArea, setProductArea] = useState('');
  const [sourceFile, setSourceFile] = useState('');
  const [goldenOpen, setGoldenOpen] = useState(false);
  const [activeGoldenId, setActiveGoldenId] = useState<string | null>(null);

  // /health is the authority on top_k, but it arrives after the first render.
  // Only adopt it while the user has not touched the control.
  const [topKTouched, setTopKTouched] = useState(false);
  useEffect(() => {
    if (!topKTouched) {
      setTopK(defaultTopK);
    }
  }, [defaultTopK, topKTouched]);

  // A document can be deleted while it is selected; falling back to "all
  // documents" beats sending a filter the backend will 404 on.
  useEffect(() => {
    if (sourceFile && !documents.includes(sourceFile)) {
      setSourceFile('');
      setActiveGoldenId(null);
    }
  }, [documents, sourceFile]);

  // `activeGoldenId` means "the box currently holds this golden question, and
  // the scope came with it". Anything that empties or rewrites the box drops the
  // highlight; the document scope itself survives, because the Document filter
  // is an independent control and widening the search behind the user's back
  // would be worse than leaving it pinned.
  const activeQuestionText = activeGoldenId
    ? goldenQuestions.find((question) => question.id === activeGoldenId)?.question
    : undefined;

  const submit = () => {
    const next = value.trim();
    if (!next) {
      return;
    }
    onSend(next, {
      mode,
      topK,
      productArea: sourceFile ? null : productArea || null,
      sourceFile: sourceFile || null,
    });
    setValue('');
    setActiveGoldenId(null);
    // Collapse the golden panel on send. It is a tall list and the answer lands
    // above it, so leaving it open pushes the thing the user just asked for off
    // screen. Same state the toggle writes, so reopening is one click.
    setGoldenOpen(false);
  };

  /**
   * Scoping to a document and unselecting go through one place, so the golden
   * panel, the group headers, and the Document dropdown can never disagree
   * about what is scoped. Clearing also drops the golden highlight, since the
   * question is no longer pinned to its document.
   */
  const selectDocument = (next: string) => {
    setSourceFile(next);
    if (!next) {
      setActiveGoldenId(null);
    }
    if (next) {
      setProductArea('');
    }
  };

  const pickGolden = (question: GoldenQuestion) => {
    // Clicking the selected question again unselects its document. The text
    // stays in the box - the usual reason to unselect is to ask that same
    // question across the whole corpus.
    if (activeGoldenId === question.id) {
      selectDocument('');
      return;
    }
    setValue(question.question);
    // A contrast question only demonstrates anything against the whole corpus.
    // Its point is that KB-007's near-duplicate plan packs out-rank the answer
    // under Week 3 - and scoping to the answer's own document removes exactly
    // those competitors, so both modes would answer and the demo would show
    // nothing. These clear the scope instead of setting it.
    selectDocument(question.contrast ? '' : question.source_file);
    setActiveGoldenId(question.id);
  };

  return (
    <form
      className="chat-input"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <GoldenQuestions
        questions={goldenQuestions}
        open={goldenOpen}
        onToggle={() => setGoldenOpen((current) => !current)}
        onPick={pickGolden}
        disabled={disabled}
        activeId={activeGoldenId}
      />

      <RetrievalControls
        mode={mode}
        onModeChange={setMode}
        topK={topK}
        onTopKChange={(next) => {
          setTopKTouched(true);
          setTopK(next);
        }}
        productArea={productArea}
        onProductAreaChange={setProductArea}
        productAreas={productAreas}
        sourceFile={sourceFile}
        onSourceFileChange={selectDocument}
        documents={documents}
        disabled={disabled}
        hybridAvailable={hybridAvailable}
        rerankerAvailable={rerankerAvailable}
      />

      <div className="chat-input-row">
        <label className="visually-hidden" htmlFor="chat-message">
          Ask a question about your documents
        </label>
        <TextArea
          id="chat-message"
          value={value}
          onChange={(event) => {
            const next = event.target.value;
            setValue(next);
            // Typing over a golden question drops its highlight but keeps the
            // document scope: the filter is an independent control, and
            // silently widening the search on a keystroke would be worse.
            if (activeGoldenId && next !== activeQuestionText) {
              setActiveGoldenId(null);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={
            sourceFile
              ? `Ask about ${sourceFile}…`
              : 'Ask about the uploaded documents…'
          }
          disabled={disabled}
          rows={2}
        />
        <Button type="submit" disabled={disabled || !value.trim()}>
          Send
        </Button>
      </div>
    </form>
  );
}
