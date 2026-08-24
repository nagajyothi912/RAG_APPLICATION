import type { ChangeEventHandler, KeyboardEventHandler } from 'react';

type TextAreaProps = {
  value: string;
  onChange: ChangeEventHandler<HTMLTextAreaElement>;
  onKeyDown?: KeyboardEventHandler<HTMLTextAreaElement>;
  placeholder?: string;
  disabled?: boolean;
  rows?: number;
  id?: string;
};

export default function TextArea({
  value,
  onChange,
  onKeyDown,
  placeholder,
  disabled,
  rows = 2,
  id,
}: TextAreaProps) {
  return (
    <textarea
      id={id}
      className="text-area"
      value={value}
      onChange={onChange}
      onKeyDown={onKeyDown}
      placeholder={placeholder}
      disabled={disabled}
      rows={rows}
    />
  );
}
