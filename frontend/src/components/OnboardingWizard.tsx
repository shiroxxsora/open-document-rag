import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getSettings } from '../api';

type Props = {
  onComplete: () => void;
};

export function OnboardingWizard({ onComplete }: Props) {
  const [step, setStep] = useState(1);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then((settings) => {
        if (settings.has_llm_api_key) {
          onComplete();
        }
      })
      .catch(() => undefined);
  }, [onComplete]);

  return (
    <section className="panel onboardingPanel">
      <p className="eyebrow">Getting started</p>
      <h2>Welcome to SRBS</h2>
      <ol className="onboardingSteps">
        <li className={step >= 1 ? 'active' : ''}>Add your LLM API key in Settings</li>
        <li className={step >= 2 ? 'active' : ''}>Upload a PDF, DOCX, or TXT document</li>
        <li className={step >= 3 ? 'active' : ''}>Ask your first question in chat</li>
      </ol>
      <div className="onboardingActions">
        {step < 3 ? (
          <button type="button" onClick={() => setStep((value) => Math.min(3, value + 1))}>
            Next step
          </button>
        ) : (
          <button type="button" onClick={onComplete}>
            Finish onboarding
          </button>
        )}
        <Link className="secondary inlineBtn" to="/settings" onClick={() => setMessage('Open Settings to save your API key.')}>
          Open settings
        </Link>
      </div>
      {message ? <p className="muted">{message}</p> : null}
    </section>
  );
}
