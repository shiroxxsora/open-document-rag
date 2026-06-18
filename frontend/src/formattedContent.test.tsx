import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FormattedContent } from './formattedContent';

describe('FormattedContent', () => {
  it('renders answer paragraphs', () => {
    render(<FormattedContent text={'Line one\n\nLine two'} />);
    expect(screen.getByText(/Line one/)).toBeTruthy();
    expect(screen.getByText(/Line two/)).toBeTruthy();
  });

  it('renders headings', () => {
    render(<FormattedContent text="## Section title" />);
    expect(screen.getByText('Section title')).toBeTruthy();
  });
});
