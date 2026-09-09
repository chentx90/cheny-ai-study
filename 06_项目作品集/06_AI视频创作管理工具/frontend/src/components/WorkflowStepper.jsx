import React from 'react';

export default function WorkflowStepper({ workflowUi, onNavigate, className = 'workflow-stepper' }) {
  if (!workflowUi?.steps?.length) return null;

  return (
    <div className={className}>
      {workflowUi.steps.map((step) => (
        <button
          key={step.id}
          type="button"
          className={`workflow-step workflow-step-${step.status}`}
          title={`进入${step.label}`}
          onClick={() => onNavigate?.(step.view)}
        >
          <span className="workflow-step-dot" aria-hidden="true" />
          <span className="workflow-step-label">{step.label}</span>
        </button>
      ))}
    </div>
  );
}
