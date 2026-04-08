import React from 'react';
import { Link } from 'react-router-dom';
import { ClipboardList, FileCheck2, FolderOpen, Layers, GitCompareArrows, SlidersHorizontal } from 'lucide-react';

type WorkflowCard = {
  title: string;
  description: string;
  cta: string;
  to: string;
  icon: React.ReactNode;
  accessPoint: string;
};

const cards: WorkflowCard[] = [
  {
    title: 'Authoring & Cue Lint',
    description:
      'Use markup helpers and lint checks before processing to catch malformed SCENE/AMBIENCE/FOLEY/MUSIC directives.',
    cta: 'Open Upload Workflow',
    to: '/upload',
    icon: <FileCheck2 size={18} className="text-brand-400" />,
    accessPoint: 'Upload → Character Voice Plan → Analyze Cues',
  },
  {
    title: 'SFX Library Management',
    description:
      'Import ZIP libraries and inspect ambience/foley/music inventory for deterministic cue playback during mixing.',
    cta: 'Open SFX Library Settings',
    to: '/settings',
    icon: <FolderOpen size={18} className="text-accent-teal" />,
    accessPoint: 'Settings → Radio-play SFX Library',
  },
  {
    title: 'Rework Versioning',
    description:
      'Create a new database-backed rework revision from a completed audiobook while preserving lineage metadata.',
    cta: 'Open a Book to Rework',
    to: '/dashboard',
    icon: <Layers size={18} className="text-purple-400" />,
    accessPoint: 'Book Detail → Create Rework Version',
  },
  {
    title: 'Revision Compare',
    description:
      'Compare revisions to inspect deltas for metrics, settings, voice-plan changes, and cue count differences.',
    cta: 'Open a Book to Compare',
    to: '/dashboard',
    icon: <GitCompareArrows size={18} className="text-accent-amber" />,
    accessPoint: 'Book Detail → Revision Timeline → Compare Revisions',
  },
  {
    title: 'Mixing & Mastering Controls',
    description:
      'Tune music provider/style and re-export options while the mastering chain applies dialogue-safe loudness shaping.',
    cta: 'Open Production Controls',
    to: '/upload',
    icon: <SlidersHorizontal size={18} className="text-green-400" />,
    accessPoint: 'Upload Production Options + Book Detail Re-export Options',
  },
];

export const WorkflowHubPage: React.FC = () => {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <ClipboardList size={22} className="text-brand-400" /> Workflow Hub
        </h1>
        <p className="text-dark-400 mt-1">
          Central access points for authoring, sound design, revisioning, and quality controls.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {cards.map((card) => (
          <div
            key={card.title}
            className="bg-dark-800/60 border border-dark-700 rounded-2xl p-5 flex flex-col gap-4"
          >
            <div className="flex items-center gap-2">
              {card.icon}
              <h2 className="text-lg font-semibold text-white">{card.title}</h2>
            </div>
            <p className="text-sm text-dark-300 leading-relaxed">{card.description}</p>
            <p className="text-xs text-dark-500">
              <span className="text-dark-400 font-medium">Access:</span> {card.accessPoint}
            </p>
            <div className="pt-1">
              <Link
                to={card.to}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-brand-500/30 bg-brand-500/10 text-brand-300 text-sm font-medium hover:bg-brand-500/20 transition-colors"
              >
                {card.cta}
              </Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
