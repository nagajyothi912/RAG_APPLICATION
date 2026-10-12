import { useEffect, useState } from 'react';
import Button from '../atoms/Button';
import TextArea from '../atoms/TextArea';
import RetrievalControls from './RetrievalControls';
import { areaLabel } from '../organisms/HelpSidebar';
import GoldenQuestions from './GoldenQuestions';
import EngineSelect from './EngineSelect';
import {
  AGENT_VARIANTS,
  VARIANT_MODE,
  type AskOptions,
  type ChatEngine,
  type ChatVariant,
  type GoldenQuestion,
  type RetrievalMode,
} from '../../services/api';

/**
 * A question the admin home's sidebar puts in the box. `nonce` makes picking the
 * same question twice still apply (the user may have edited the box since).
 */
export type ChatPrefill = { text: string; sourceFile: string | null; nonce: number };

type ChatInputProps = {
  onSend: (text: string, options: AskOptions) => void;
  disabled: boolean;
  productAreas: string[];
  documents: string[];
  goldenQuestions: GoldenQuestion[];
  defaultTopK: number;
  hybridAvailable: boolean;
  rerankerAvailable: boolean;
  variant?: ChatVariant;
  /** Admin home only: what answers the question, owned by the page. */
  engine?: ChatEngine;
  onEngineChange?: (engine: ChatEngine) => void;
  /** The engine stays switchable while asking is blocked (e.g. RAG with nothing indexed). */
  engineDisabled?: boolean;
  /** Admin home only: a common question picked in the sidebar. */
  prefill?: ChatPrefill | null;
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
  variant = 'week4',
  engine = 'assistant',
  onEngineChange,
  engineDisabled = false,
  prefill = null,
}: ChatInputProps) {
  const isChatbot = variant === 'chatbot';
  // The admin home picks the engine per question; its golden set lives in the
  // sidebar's common questions rather than in the panel above the box.
  const isAdmin = variant === 'admin';
  // The MCP assistant picks its own tools and search area, so the RAG controls
  // (mode, top-k, product area, golden set) do not apply to it.
  const isAgent = AGENT_VARIANTS.includes(variant) || (isAdmin && engine === 'assistant');
  const [value, setValue] = useState('');
  const [mode, setMode] = useState<RetrievalMode>(VARIANT_MODE[variant]);
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

  useEffect(() => {
    if (!prefill) {
      return;
    }
    setValue(prefill.text);
    setSourceFile(prefill.sourceFile ?? '');
    if (prefill.sourceFile) {
      setProductArea('');
    }
    setActiveGoldenId(null);
  }, [prefill]);

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
      mode: isAdmin ? (engine === 'assistant' ? 'week4' : engine) : mode,
      topK,
      // The assistant ignores retrieval scope; leaving it off keeps the message
      // badges honest about how the question was asked.
      productArea: isAgent || sourceFile ? null : productArea || null,
      sourceFile: isAgent ? null : sourceFile || null,
      agent: isAgent,
    });
    setValue('');
    setActiveGoldenId(null);
    // On the admin home a document scope comes with one picked question; the
    // Document select is not shown there, so keeping it would silently narrow
    // the next, unrelated question.
    if (isAdmin) {
      setSourceFile('');
    }
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

  const engineSelect =
    isAdmin && onEngineChange ? (
      <EngineSelect
        value={engine}
        onChange={onEngineChange}
        disabled={engineDisabled}
        hybridAvailable={hybridAvailable}
        rerankerAvailable={rerankerAvailable}
      />
    ) : null;

  return (
    <form
      className="chat-input"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {isAdmin && isAgent && engineSelect ? <div className="retrieval-controls">{engineSelect}</div> : null}

      {isChatbot || isAgent || isAdmin ? null : (
        <GoldenQuestions
          questions={goldenQuestions}
          open={goldenOpen}
          onToggle={() => setGoldenOpen((current) => !current)}
          onPick={pickGolden}
          disabled={disabled}
          activeId={activeGoldenId}
        />
      )}

      {isAgent ? null : (
      <RetrievalControls
        leading={engineSelect}
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
        areaOptionLabel={isChatbot ? areaLabel : undefined}
        sourceFile={sourceFile}
        onSourceFileChange={selectDocument}
        documents={documents}
        disabled={disabled}
        hybridAvailable={hybridAvailable}
        rerankerAvailable={rerankerAvailable}
        showModeToggle={variant === 'week4' && !isAdmin}
        showTopK={!isChatbot}
        areaLabel={isChatbot ? 'Topic' : 'Product area'}
      />
      )}

      {isAdmin && !isAgent && sourceFile ? (
        <div className="scope-chip">
          Scoped to <strong>{sourceFile}</strong>
          <button type="button" onClick={() => setSourceFile('')} disabled={disabled}>
            Search all documents
          </button>
        </div>
      ) : null}

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
              : isAgent
                ? 'Ask about plans, billing, a connection problem, or a ticket (e.g. TCK-4471)…'
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
