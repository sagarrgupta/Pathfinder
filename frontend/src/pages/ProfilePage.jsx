import React, { useState, useEffect, useRef } from 'react';
import { useApp } from '@/context/AppContext';
import { useToast } from '@/components/shared/Toast';
import { getProfile, addProfileText, uploadDocument, deleteProfileEntity, updateProfile } from '@/services/api';
import {
  User, Upload, FileText, Trash2, Plus, BookOpen,
  Briefcase, Target, Star, GraduationCap, Loader2,
  Pencil, Check, X, AlertTriangle, Heart, Folder,
  Building2, Circle, ArrowUpDown, Calendar, Sparkles,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// ── Configuration for known entity types ────────────────────────
const ENTITY_CONFIG = {
  Course:     { label: 'Courses',     icon: BookOpen,   nameKey: 'name', sortKey: 'name',     render: (c) => `${c.code || c.name || '?'} ${c.grade ? `(${c.grade})` : ''}`.trim() },
  Skill:      { label: 'Skills',      icon: Star,       nameKey: 'name', sortKey: 'name',     render: (s) => `${s.name || '?'} ${s.proficiency ? `— ${s.proficiency}` : ''}`.trim() },
  Company:    { label: 'Experience',   icon: Briefcase,  nameKey: 'name', sortKey: null,       cardMode: true },
  Goal:       { label: 'Goals',        icon: Target,     nameKey: 'name', sortKey: null,       render: (g) => g.name || g.description || 'Goal' },
  Interest:   { label: 'Interests',    icon: Heart,      nameKey: 'name', sortKey: 'name',     render: (i) => i.name || 'Interest' },
  Project:    { label: 'Projects',     icon: Folder,     nameKey: 'name', sortKey: null,       render: (p) => `${p.name || 'Project'} ${p.status ? `(${p.status})` : ''}`.trim() },
  Department: { label: 'Departments',  icon: Building2,  nameKey: 'name', sortKey: 'name',     render: (d) => d.name || 'Department' },
  Document:   { label: 'Documents',    icon: FileText,   nameKey: 'filename', sortKey: null,   render: (d) => `${d.filename || d.name || 'Document'} [${d.scope || 'global'}]` },
};

const HIDDEN_PERSONAL_FIELDS = new Set(['id', 'created_at', 'updated_at', '_relationship']);

const LABEL_OVERRIDES = { gpa: 'GPA', id: 'ID', url: 'URL' };

function formatFieldLabel(key) {
  if (LABEL_OVERRIDES[key.toLowerCase()]) return LABEL_OVERRIDES[key.toLowerCase()];
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function getEntityConfig(label) {
  return ENTITY_CONFIG[label] || {
    label: label + 's', icon: Circle, nameKey: 'name', sortKey: null,
    render: (item) => item.name || item.title || JSON.stringify(item).slice(0, 60),
  };
}

// ── Skeleton component ──────────────────────────────────────────
function Skeleton({ className }) {
  return <div className={cn('skeleton', className)} />;
}

function ProfileSkeleton() {
  return (
    <div className="space-y-3">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="flex items-center justify-between py-2 px-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-40" />
        </div>
      ))}
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────

export default function ProfilePage() {
  const { state, dispatch } = useApp();
  const toast = useToast();
  const [activeTab, setActiveTab] = useState('personal');
  const [freeText, setFreeText] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [isProcessingText, setIsProcessingText] = useState(false);
  const [processingStep, setProcessingStep] = useState('');
  const fileInputRef = useRef(null);
  const profile = state.profile;

  useEffect(() => {
    loadProfile();
  }, []);

  const loadProfile = async () => {
    dispatch({ type: 'SET_PROFILE_LOADING', payload: true });
    try {
      const data = await getProfile();
      dispatch({ type: 'SET_PROFILE', payload: data });
    } catch (err) {
      console.error('Failed to load profile:', err);
      dispatch({ type: 'SET_PROFILE_LOADING', payload: false });
    }
  };

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    setProcessingStep('Uploading document...');
    try {
      setProcessingStep('Processing and extracting entities...');
      const result = await uploadDocument(file, 'global');
      toast.success(`Uploaded ${file.name}: ${result.entities_extracted} entities extracted`);
      setProcessingStep('');
      await loadProfile();
    } catch (err) {
      toast.error(`Upload failed: ${err.message}`);
      setProcessingStep('');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleAddText = async () => {
    if (!freeText.trim()) return;
    setIsProcessingText(true);
    setProcessingStep('Analyzing your text...');
    try {
      setProcessingStep('Extracting entities and updating knowledge graph...');
      const result = await addProfileText(freeText);
      toast.success(`Extracted ${result.entities_extracted} entities from your text`);
      setFreeText('');
      setProcessingStep('Refreshing profile...');
      await loadProfile();
      setProcessingStep('');
    } catch (err) {
      toast.error(`Failed: ${err.message}`);
      setProcessingStep('');
    } finally {
      setIsProcessingText(false);
    }
  };

  const handleDelete = async (label, name) => {
    if (!window.confirm(`Delete "${name}" from your profile?`)) return;
    try {
      await deleteProfileEntity(label, name);
      toast.success(`Deleted ${name}`);
      await loadProfile();
    } catch (err) {
      toast.error(`Delete failed: ${err.message}`);
    }
  };

  const handleEditField = async (field, value) => {
    try {
      await updateProfile(field, value);
      toast.success(`Updated ${formatFieldLabel(field)}`);
      await loadProfile();
    } catch (err) {
      toast.error(`Update failed: ${err.message}`);
    }
  };

  const isProcessing = isUploading || isProcessingText;

  // ── Build dynamic tabs ──────────────────────────────────────
  const tabs = [{ id: 'personal', label: 'Personal', icon: User, count: null }];

  if (profile?.all_entities) {
    const PREFERRED_ORDER = ['Course', 'Skill', 'Company', 'Goal', 'Interest', 'Project', 'Department', 'Document'];
    const entityLabels = Object.keys(profile.all_entities);

    const ordered = [
      ...PREFERRED_ORDER.filter((l) => entityLabels.includes(l)),
      ...entityLabels.filter((l) => !PREFERRED_ORDER.includes(l)).sort(),
    ];

    for (const label of ordered) {
      const items = profile.all_entities[label] || [];
      if (items.length > 0 || label === 'Document') {
        const config = getEntityConfig(label);
        tabs.push({ id: label, label: config.label, icon: config.icon, count: items.length });
      }
    }
  }

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade">
      <div className="max-w-4xl mx-auto p-6 animate-fade-in">
        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/10 flex items-center justify-center">
            <GraduationCap className="h-7 w-7 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">My Profile</h1>
            <p className="text-muted-foreground text-sm mt-0.5">
              Manage your academic data. Upload documents or add information directly.
            </p>
          </div>
        </div>

        {/* Processing Banner */}
        {isProcessing && processingStep && (
          <div className="mb-6 p-4 rounded-xl bg-yellow-50 dark:bg-yellow-950/50 border border-yellow-200 dark:border-yellow-800 flex items-center gap-3 animate-fade-in-up">
            <Loader2 className="h-5 w-5 animate-spin text-yellow-600 dark:text-yellow-400" />
            <div>
              <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200">{processingStep}</p>
              <p className="text-xs text-yellow-600 dark:text-yellow-400 flex items-center gap-1 mt-0.5">
                <AlertTriangle className="h-3 w-3" />
                Please do not refresh or navigate away.
              </p>
            </div>
          </div>
        )}

        {/* Input Section */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
          {/* Document Upload */}
          <div className="rounded-xl border bg-card p-5 hover:shadow-sm transition-shadow">
            <h3 className="font-semibold mb-1.5 flex items-center gap-2">
              <Upload className="h-4 w-4 text-primary" /> Upload Document
            </h3>
            <p className="text-xs text-muted-foreground mb-4">
              Upload transcripts, resumes, or other academic documents (PDF).
            </p>
            <input ref={fileInputRef} type="file" accept=".pdf" onChange={handleUpload} className="hidden" />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isProcessing}
              className="w-full py-2.5 border-2 border-dashed rounded-lg text-sm hover:bg-accent hover:border-primary/20 transition-all disabled:opacity-50 flex items-center justify-center gap-2 active:scale-[0.98]"
            >
              {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {isUploading ? 'Processing...' : 'Select PDF File'}
            </button>
          </div>

          {/* Free Text Input */}
          <div className="rounded-xl border bg-card p-5 hover:shadow-sm transition-shadow">
            <h3 className="font-semibold mb-1.5 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" /> Add Information
            </h3>
            <p className="text-xs text-muted-foreground mb-4">
              Type anything about yourself — we'll extract and store it intelligently.
            </p>
            <textarea
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              placeholder='e.g., "I have 2 years of Python experience and my GPA is 3.7..."'
              className="w-full rounded-lg border bg-background px-3 py-2.5 text-sm resize-none h-20 focus:outline-none focus:ring-2 focus:ring-ring/50 transition-shadow"
              disabled={isProcessing}
            />
            <button
              onClick={handleAddText}
              disabled={!freeText.trim() || isProcessing}
              className="mt-2 w-full py-2.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
            >
              {isProcessingText ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {isProcessingText ? 'Processing...' : 'Add to Profile'}
            </button>
          </div>
        </div>

        {/* Profile Tabs */}
        <div className="rounded-xl border bg-card overflow-hidden">
          <div className="flex border-b overflow-x-auto scrollbar-fade bg-muted/30">
            {tabs.map(({ id, label, icon: Icon, count }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={cn(
                  'flex items-center gap-1.5 px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-all',
                  activeTab === id
                    ? 'border-primary text-primary bg-card'
                    : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-card/50'
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
                {count !== null && count > 0 && (
                  <span className={cn(
                    'text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[20px] text-center',
                    activeTab === id
                      ? 'bg-primary/10 text-primary'
                      : 'bg-muted text-muted-foreground'
                  )}>
                    {count}
                  </span>
                )}
              </button>
            ))}
          </div>

          <div className="p-5">
            {state.profileLoading ? (
              <ProfileSkeleton />
            ) : !profile ? (
              <div className="text-center py-12">
                <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mx-auto mb-3">
                  <User className="h-6 w-6 text-muted-foreground" />
                </div>
                <p className="text-muted-foreground text-sm">
                  No profile data yet. Upload a document or add information above.
                </p>
              </div>
            ) : activeTab === 'personal' ? (
              <DynamicPersonalTab personal={profile.personal} onEditField={handleEditField} />
            ) : (
              <DynamicEntityTab
                label={activeTab}
                items={profile.all_entities?.[activeTab] || []}
                onDelete={handleDelete}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Dynamic Personal Tab ────────────────────────────────────────

function DynamicPersonalTab({ personal, onEditField }) {
  if (!personal) return <EmptyTab />;

  const entries = Object.entries(personal)
    .filter(([key, value]) => !HIDDEN_PERSONAL_FIELDS.has(key) && value != null && String(value).trim() !== '')
    .sort(([a], [b]) => {
      const order = ['name', 'university', 'program', 'gpa', 'semester', 'email'];
      const ai = order.indexOf(a);
      const bi = order.indexOf(b);
      if (ai >= 0 && bi >= 0) return ai - bi;
      if (ai >= 0) return -1;
      if (bi >= 0) return 1;
      return a.localeCompare(b);
    });

  return entries.length > 0 ? (
    <div className="space-y-0.5">
      {entries.map(([key, value]) => (
        <EditableField
          key={key}
          label={formatFieldLabel(key)}
          value={String(value)}
          fieldKey={key}
          onSave={onEditField}
        />
      ))}
    </div>
  ) : <EmptyTab />;
}

// ── Dynamic Entity Tab ──────────────────────────────────────────

function DynamicEntityTab({ label, items, onDelete }) {
  if (!items || items.length === 0) return <EmptyTab />;

  const config = getEntityConfig(label);
  const [sortAsc, setSortAsc] = useState(true);

  const sortedItems = React.useMemo(() => {
    if (!config.sortKey) return items;
    return [...items].sort((a, b) => {
      const aVal = (a[config.sortKey] || '').toLowerCase();
      const bVal = (b[config.sortKey] || '').toLowerCase();
      return sortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });
  }, [items, config.sortKey, sortAsc]);

  if (config.cardMode) {
    return (
      <div className="space-y-3">
        {sortedItems.map((item, i) => (
          <ExperienceCard key={i} item={item} onDelete={() => onDelete(label, item[config.nameKey] || item.name || '')} />
        ))}
      </div>
    );
  }

  return (
    <div>
      {config.sortKey && sortedItems.length > 1 && (
        <div className="flex justify-end mb-2">
          <button
            onClick={() => setSortAsc(!sortAsc)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors px-2.5 py-1.5 rounded-lg hover:bg-muted"
          >
            <ArrowUpDown className="h-3 w-3" />
            {sortAsc ? 'A → Z' : 'Z → A'}
          </button>
        </div>
      )}

      <div className="space-y-0.5">
        {sortedItems.map((item, i) => (
          <div key={i} className="flex items-center justify-between py-2.5 px-3 rounded-lg hover:bg-muted/50 group transition-colors">
            <span className="text-sm">{config.render(item)}</span>
            <button
              onClick={() => onDelete(label, item[config.nameKey] || item.name || item.filename || '')}
              className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all p-1 rounded-md hover:bg-destructive/10"
              title="Delete"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Experience Card ─────────────────────────────────────────────

function ExperienceCard({ item, onDelete }) {
  const name = item.name || 'Company';
  const title = item.title || item.role || '';
  const description = item.description || '';
  const startDate = item.start_date || item.startDate || '';
  const endDate = item.end_date || item.endDate || '';

  return (
    <div className="rounded-xl border p-4 hover:bg-muted/30 hover:shadow-sm transition-all group">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold">{name}</span>
            {title && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                {title}
              </span>
            )}
          </div>

          {(startDate || endDate) && (
            <div className="flex items-center gap-1.5 mt-1.5 text-xs text-muted-foreground">
              <Calendar className="h-3 w-3" />
              <span>{startDate || '?'} — {endDate || 'Present'}</span>
            </div>
          )}

          {description && (
            <p className="mt-2 text-sm text-muted-foreground leading-relaxed line-clamp-3">
              {description}
            </p>
          )}
        </div>

        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all ml-3 mt-0.5 flex-shrink-0 p-1 rounded-md hover:bg-destructive/10"
          title="Delete"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Editable Field ──────────────────────────────────────────────

function EditableField({ label, value, fieldKey, onSave }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  const handleSave = () => {
    if (draft !== value) {
      onSave(fieldKey, draft);
    }
    setEditing(false);
  };

  const handleCancel = () => {
    setDraft(value);
    setEditing(false);
  };

  return (
    <div className="flex items-center justify-between py-2.5 px-3 rounded-lg hover:bg-muted/30 group transition-colors">
      <span className="text-muted-foreground text-sm w-28 flex-shrink-0 font-medium">{label}</span>
      {editing ? (
        <div className="flex items-center gap-2 flex-1 ml-4 animate-fade-in">
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="flex-1 rounded-lg border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSave();
              if (e.key === 'Escape') handleCancel();
            }}
          />
          <button onClick={handleSave} className="p-1 rounded-md text-green-600 hover:bg-green-100 dark:hover:bg-green-900/30 transition-colors" title="Save">
            <Check className="h-4 w-4" />
          </button>
          <button onClick={handleCancel} className="p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors" title="Cancel">
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2 flex-1 ml-4 justify-end">
          <span className="text-sm font-medium">{value || '—'}</span>
          <button
            onClick={() => { setDraft(value || ''); setEditing(true); }}
            className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground transition-all p-1 rounded-md hover:bg-accent"
            title="Edit"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

function EmptyTab() {
  return (
    <div className="text-center py-10">
      <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center mx-auto mb-3">
        <FileText className="h-5 w-5 text-muted-foreground/50" />
      </div>
      <p className="text-muted-foreground text-sm">No data available yet.</p>
    </div>
  );
}
