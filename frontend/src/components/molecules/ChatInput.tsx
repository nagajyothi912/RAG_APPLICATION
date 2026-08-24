import { useState } from 'react';
import Button from '../atoms/Button';
import TextArea from '../atoms/TextArea';

type ChatInputProps = {
  onSend: (text: string) => void;
  disabled: boolean;
};

export default function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState('');

  const submit = () => {
    const next = value.trim();
    if (!next) {
      return;
    }
    onSend(next);
    setValue('');
  };

  return (
    <form
      className="chat-input"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label className="visually-hidden" htmlFor="chat-message">
        Ask a question about your documents
      </label>
      <TextArea
        id="chat-message"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder="Ask about the uploaded documents…"
        disabled={disabled}
        rows={2}
      />
      <Button type="submit" disabled={disabled || !value.trim()}>
        Send
      </Button>
    </form>
  );
}
