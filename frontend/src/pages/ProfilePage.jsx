import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '@/context/AppContext';
import { useToast } from '@/components/shared/Toast';
import { getProfile, addProfileText, uploadDocument, deleteProfileEntity, updateProfile, updateProfileEntity, checkDocumentExists } from '@/services/api';
import {
  User, Upload, FileText, Trash2, Plus, BookOpen,
  Briefcase, Target, Star, GraduationCap, Loader2,
  Pencil, Check, X, AlertTriangle, Heart, Folder,
  Building2, Circle, ArrowUpDown, Calendar, Sparkles, Brain, ShieldCheck, FileSearch, Network, Clock3,
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
  CandidateFact: { label: 'Candidate Facts', icon: Brain, nameKey: 'value', sortKey: null, cardMode: 'memory' },
  MemoryItem: { label: 'Memories', icon: Network, nameKey: 'summary', sortKey: null, cardMode: 'memory' },
  Evidence: { label: 'Evidence', icon: FileSearch, nameKey: 'id', sortKey: null, cardMode: 'evidence' },
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

function toTitleCase(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatShortDate(value) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function clampText(value, max = 220) {
  const text = String(value || '').trim();
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max).trim()}…` : text;
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

function SectionCard({ className, children }) {
  return (
    <div className={cn('rounded-2xl border bg-card shadow-sm', className)}>
      {children}
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────

export default function ProfilePage() {
  const navigate = useNavigate();
  const { state, dispatch } = useApp();
  const studentId = state.activeStudentId;
  const toast = useToast();
  const [activeTab, setActiveTab] = useState('personal');
  const [freeText, setFreeText] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [isProcessingText, setIsProcessingText] = useState(false);
  const [processingStep, setProcessingStep] = useState('');
  const fileInputRef = useRef(null);
  const profile = state.profile;

  // Confirmation dialog state
  const [confirmDialog, setConfirmDialog] = useState({
    open: false, title: '', message: '', onConfirm: null,
    confirmLabel: 'Delete', variant: 'destructive',
  });

  useEffect(() => {
    if (!studentId) return;
    loadProfile();
  }, [studentId]);

  const loadProfile = async () => {
    dispatch({ type: 'SET_PROFILE_LOADING', payload: true });
    try {
      const data = await getProfile(studentId);
      dispatch({ type: 'SET_PROFILE', payload: data });
    } catch (err) {
      console.error('Failed to load profile:', err);
      dispatch({ type: 'SET_PROFILE_LOADING', payload: false });
    }
  };

  const performUpload = async (file, replace = false) => {
    setIsUploading(true);
    setProcessingStep('Uploading document...');
    try {
      setProcessingStep('Processing and extracting entities...');
      const result = await uploadDocument(file, 'global', null, replace, studentId);
      toast.success(
        replace
          ? `Replaced ${file.name}: ${result.entities_extracted} entities extracted`
          : `Uploaded ${file.name}: ${result.entities_extracted} entities extracted`
      );
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

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Check for duplicate
    try {
      const { exists } = await checkDocumentExists(file.name, studentId);
      if (exists) {
        setConfirmDialog({
          open: true,
          title: 'Duplicate Document',
          message: `"${file.name}" already exists in your profile. Would you like to replace it with the new version?`,
          confirmLabel: 'Replace',
          variant: 'primary',
          onConfirm: () => {
            setConfirmDialog((prev) => ({ ...prev, open: false }));
            performUpload(file, true);
          },
        });
        return;
      }
    } catch {
      // If check fails, proceed with upload anyway
    }

    performUpload(file);
  };

  const handleAddText = async () => {
    if (!freeText.trim()) return;
    setIsProcessingText(true);
    setProcessingStep('Analyzing your text...');
    try {
      setProcessingStep('Extracting entities and updating knowledge graph...');
      const result = await addProfileText(freeText, studentId);
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

  const handleDelete = (label, name) => {
    setConfirmDialog({
      open: true,
      title: 'Confirm Deletion',
      message: `Are you sure you want to delete "${name}" from your profile? This action cannot be undone.`,
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, open: false }));
        try {
          await deleteProfileEntity(label, name, studentId);
          toast.success(`Deleted ${name}`);
          await loadProfile();
        } catch (err) {
          toast.error(`Delete failed: ${err.message}`);
        }
      },
    });
  };

  const closeConfirmDialog = () => setConfirmDialog((prev) => ({ ...prev, open: false }));

  const handleEditField = async (field, value) => {
    try {
      await updateProfile(field, value, studentId);
      toast.success(`Updated ${formatFieldLabel(field)}`);
      await loadProfile();
    } catch (err) {
      toast.error(`Update failed: ${err.message}`);
    }
  };

  const handleEditEntity = async (label, name, properties) => {
    try {
      await updateProfileEntity(label, name, properties, studentId);
      toast.success(`Updated ${name}`);
      await loadProfile();
    } catch (err) {
      toast.error(`Update failed: ${err.message}`);
    }
  };

  const isProcessing = isUploading || isProcessingText;
  const completenessChecklist = [
    { label: 'Name', done: !!profile?.personal?.name, hint: 'Add your name in Personal.' },
    { label: 'University', done: !!profile?.personal?.university, hint: 'Add your university in Personal.' },
    { label: 'Program', done: !!profile?.personal?.program, hint: 'Add your degree or major in Personal.' },
    { label: 'GPA', done: !!profile?.personal?.gpa, hint: 'Upload a transcript or add your GPA in Personal.' },
    { label: 'Semester', done: !!profile?.personal?.semester, hint: 'Add your current semester in Personal.' },
    { label: 'Email', done: !!profile?.personal?.email, hint: 'Add an email so your profile is more complete.' },
    { label: 'Skills', done: (profile?.skills?.length || 0) > 0, hint: 'Add skills or upload a resume.' },
    { label: 'Goals', done: (profile?.goals?.length || 0) > 0, hint: 'Add your goals in plain language.' },
    { label: 'Documents', done: (profile?.documents?.length || 0) > 0, hint: 'Upload a resume, transcript, or supporting document.' },
  ];
  const missingCoverageItems = completenessChecklist.filter((item) => !item.done);

  // ── Build dynamic tabs ──────────────────────────────────────
  const tabs = [{ id: 'personal', label: 'Personal', icon: User, count: null }];

  if (profile?.all_entities) {
    const PREFERRED_ORDER = ['Course', 'Skill', 'Company', 'Goal', 'Interest', 'Project', 'Department', 'Document', 'CandidateFact', 'MemoryItem', 'Evidence'];
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
      <ConfirmDialog
        open={confirmDialog.open}
        title={confirmDialog.title}
        message={confirmDialog.message}
        onConfirm={confirmDialog.onConfirm}
        onCancel={closeConfirmDialog}
        confirmLabel={confirmDialog.confirmLabel}
        variant={confirmDialog.variant}
      />
      <div className="mx-auto max-w-4xl space-y-6 p-6 animate-fade-in">
        {/* Header */}
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/10 flex items-center justify-center">
            <GraduationCap className="h-7 w-7 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">My Profile</h1>
            <p className="text-muted-foreground text-sm mt-0.5">
              Keep student context accurate so answers stay grounded and personal.
            </p>
          </div>
        </div>

        {profile && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.3fr_0.7fr]">
            <SectionCard className="p-5">
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-base font-semibold tracking-tight">Profile coverage</h2>
                    <p className="mt-1 text-sm text-muted-foreground">
                      This score goes up as you add the core details Pathfinder needs to personalize answers well.
                    </p>
                  </div>
                  <p className="pt-0.5 text-sm font-medium text-foreground">
                    {Math.round((profile.completeness || 0) * 100)}%
                  </p>
                </div>

                <div className="space-y-2">
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{ width: `${Math.max(4, Math.round((profile.completeness || 0) * 100))}%` }}
                    />
                  </div>
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{completenessChecklist.filter((item) => item.done).length} of {completenessChecklist.length} core items added</span>
                    <span>{missingCoverageItems.length} left</span>
                  </div>
                </div>

                {missingCoverageItems.length > 0 && (
                  <div className="rounded-2xl border border-primary/15 bg-primary/5 p-4">
                    <p className="text-sm font-medium text-foreground">How to increase this score</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {missingCoverageItems.slice(0, 4).map((item) => (
                        <div
                          key={item.label}
                          className="rounded-full border bg-background px-3 py-1.5 text-xs text-muted-foreground"
                          title={item.hint}
                        >
                          Add {item.label}
                        </div>
                      ))}
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Fastest ways: fill missing personal fields, add your goals in plain language, or upload a transcript/resume.
                    </p>
                  </div>
                )}

                <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-3">
                  {completenessChecklist.map((item) => (
                    <div
                      key={item.label}
                      className={cn(
                        'rounded-xl border px-3 py-2 text-sm',
                        item.done
                          ? 'border-emerald-500/20 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300'
                          : 'border-border bg-muted/30 text-muted-foreground'
                      )}
                    >
                      <div className="flex items-center gap-2">
                        {item.done ? <Check className="h-3.5 w-3.5" /> : <Circle className="h-3.5 w-3.5" />}
                        <span className="font-medium">{item.label}</span>
                      </div>
                      {!item.done && (
                        <p className="mt-1 text-xs text-muted-foreground">{item.hint}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </SectionCard>

            <div className="space-y-4">
              <ProfileMetricCard
                label="Memory reliability"
                value={`${Math.round((profile.confidence || 0) * 100)}%`}
                description="How trustworthy Pathfinder believes the stored facts are after evidence checks, deduping, and conflict cleanup. This improves as evidence becomes clearer and conflicts are resolved."
                tone={(profile.confidence || 0) >= 0.7 ? 'good' : 'warn'}
                icon={ShieldCheck}
              />
              <ProfileMetricCard
                label="Knowledge coverage"
                value={`${profile.memory_overview?.candidate_facts || 0} facts`}
                description={`${profile.memory_overview?.memory_items || 0} memories and ${profile.memory_overview?.evidence || 0} evidence items available.`}
                icon={Brain}
              />
              {(profile.memory_overview?.conflicts || 0) > 0 && (
                <div className="rounded-2xl border border-amber-200 bg-amber-50/70 p-5 shadow-sm dark:border-amber-900/40 dark:bg-amber-950/20">
                  <div className="mb-2 flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-300" />
                    <p className="text-xs font-semibold uppercase tracking-widest text-amber-700 dark:text-amber-300">
                      Needs review
                    </p>
                  </div>
                  <p className="text-xl font-bold tracking-tight">
                    {profile.memory_overview?.conflicts || 0} open conflict{(profile.memory_overview?.conflicts || 0) === 1 ? '' : 's'}
                  </p>
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                    Resolve conflicting profile signals so future recommendations use the right current context.
                  </p>
                  <button
                    onClick={() => navigate('/profile/conflicts')}
                    className="mt-4 inline-flex items-center gap-2 rounded-xl bg-amber-600 px-4 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
                  >
                    Resolve conflicts
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Processing Banner */}
        {isProcessing && processingStep && (
          <div className="flex items-center gap-3 rounded-2xl border border-yellow-200 bg-yellow-50 p-4 shadow-sm animate-fade-in-up dark:border-yellow-800 dark:bg-yellow-950/50">
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
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {/* Document Upload */}
          <SectionCard className="p-5 transition-shadow hover:shadow-md">
            <h3 className="mb-1.5 flex items-center gap-2 font-semibold">
              <Upload className="h-4 w-4 text-primary" /> Upload Document
            </h3>
            <p className="mb-4 text-sm text-muted-foreground">
              Add a resume, transcript, or supporting document to strengthen profile evidence.
            </p>
            <input ref={fileInputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.heif,.heic,.docx" onChange={handleUpload} className="hidden" />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isProcessing}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed py-2.5 text-sm transition-all hover:border-primary/20 hover:bg-accent disabled:opacity-50 active:scale-[0.98]"
            >
              {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {isUploading ? 'Processing...' : 'Select File'}
            </button>
          </SectionCard>

          {/* Free Text Input */}
          <SectionCard className="p-5 transition-shadow hover:shadow-md">
            <h3 className="mb-1.5 flex items-center gap-2 font-semibold">
              <Sparkles className="h-4 w-4 text-primary" /> Add Information
            </h3>
            <p className="mb-4 text-sm text-muted-foreground">
              Add a short summary in plain language. Pathfinder will extract and remember what matters.
            </p>
            <textarea
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              placeholder='e.g., "I am a CS student at Sacramento State, I want backend internships, I prefer remote roles, and I’m strongest in Python and SQL."'
              className="h-24 w-full resize-none rounded-xl border bg-background px-3 py-2.5 text-sm transition-shadow focus:outline-none focus:ring-2 focus:ring-ring/50"
              disabled={isProcessing}
            />
            <button
              onClick={handleAddText}
              disabled={!freeText.trim() || isProcessing}
              className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-2.5 text-sm font-medium text-primary-foreground transition-all hover:opacity-90 disabled:opacity-40 active:scale-[0.98]"
            >
              {isProcessingText ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {isProcessingText ? 'Processing...' : 'Add to Profile'}
            </button>
          </SectionCard>
        </div>

        {/* Profile Tabs */}
        <SectionCard className="overflow-hidden">
          <div className="flex overflow-x-auto border-b bg-muted/15 px-2 scrollbar-fade">
            {tabs.map(({ id, label, icon: Icon, count }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={cn(
                  'my-2 flex items-center gap-1.5 whitespace-nowrap rounded-xl border px-3.5 py-2 text-sm font-medium transition-all',
                  activeTab === id
                    ? 'border-primary/20 bg-primary/5 text-primary'
                    : 'border-transparent text-muted-foreground hover:bg-card/70 hover:text-foreground'
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
                {count !== null && count > 0 && (
                  <span className={cn(
                    'min-w-[20px] rounded-full px-1.5 py-0.5 text-center text-[10px] font-bold',
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
              <div className="py-12 text-center">
                <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-muted">
                  <User className="h-6 w-6 text-muted-foreground" />
                </div>
                <h3 className="text-base font-semibold tracking-tight">No profile data yet</h3>
                <p className="mt-1 text-sm text-muted-foreground">Upload a document or add a short summary to start building this profile.</p>
              </div>
            ) : activeTab === 'personal' ? (
              <DynamicPersonalTab personal={profile.personal} onEditField={handleEditField} />
            ) : (
              <DynamicEntityTab
                label={activeTab}
                items={profile.all_entities?.[activeTab] || []}
                onDelete={handleDelete}
                onEdit={handleEditEntity}
              />
            )}
          </div>
        </SectionCard>
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
      <div className="space-y-1">
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

function ProfileMetricCard({ label, value, description, tone = 'neutral', icon: Icon }) {
  const toneClasses = {
    good: 'border-emerald-200 bg-emerald-50/70 dark:border-emerald-900/40 dark:bg-emerald-950/20',
    warn: 'border-amber-200 bg-amber-50/70 dark:border-amber-900/40 dark:bg-amber-950/20',
    neutral: 'border-border bg-card',
  };

  return (
    <div className={cn('rounded-2xl border p-5 shadow-sm', toneClasses[tone] || toneClasses.neutral)}>
      <div className="mb-2 flex items-center gap-2">
        {Icon ? <Icon className="h-4 w-4 text-primary" /> : null}
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">{label}</p>
      </div>
      <p className="text-xl font-bold tracking-tight">{value}</p>
      <p className="text-xs text-muted-foreground mt-2 leading-relaxed">{description}</p>
    </div>
  );
}

// ── Dynamic Entity Tab ──────────────────────────────────────────

function DynamicEntityTab({ label, items, onDelete, onEdit }) {
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
          config.cardMode === 'memory' ? (
            <MemoryCard
              key={i}
              label={label}
              item={item}
              onDelete={() => onDelete(label, item[config.nameKey] || item.name || item.id || '')}
            />
          ) : config.cardMode === 'evidence' ? (
            <EvidenceCard
              key={i}
              item={item}
              onDelete={() => onDelete(label, item.id || item[config.nameKey] || '')}
            />
          ) : (
            <ExperienceCard
              key={i}
              label={label}
              item={item}
              onDelete={() => onDelete(label, item[config.nameKey] || item.name || '')}
              onEdit={onEdit}
            />
          )
        ))}
      </div>
    );
  }

  return (
    <div>
      {config.sortKey && sortedItems.length > 1 && (
        <div className="mb-3 flex justify-end">
          <button
            onClick={() => setSortAsc(!sortAsc)}
            className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <ArrowUpDown className="h-3 w-3" />
            {sortAsc ? 'A → Z' : 'Z → A'}
          </button>
        </div>
      )}

      <div className="space-y-1">
        {sortedItems.map((item, i) => (
          <div key={i} className="group flex items-center justify-between rounded-xl border border-transparent px-3 py-3 transition-colors hover:border-border/60 hover:bg-muted/35">
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

function MemoryCard({ label, item, onDelete }) {
  const title = label === 'CandidateFact'
    ? (item.value || 'Candidate fact')
    : (item.title || item.summary || 'Memory');
  const subtitle = label === 'CandidateFact'
    ? toTitleCase(item.fact_type || 'fact')
    : toTitleCase(item.memory_type || 'memory');
  const confidence = Math.round((Number(item.confidence) || 0) * 100);
  const salience = Math.round((Number(item.salience) || 0) * 100);
  const status = toTitleCase(item.status || 'candidate');
  const source = item.source_ref || item.source_type || item._source_document || 'Unknown source';
  const updated = formatShortDate(item.last_reinforced_at || item.updated_at || item.created_at);
  const summary = clampText(item.summary || item.metadata?.summary || item.value, 180);

  return (
    <div className="group rounded-2xl border bg-card p-4 shadow-sm transition-colors hover:border-border/70 hover:bg-muted/10">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">{subtitle}</span>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">{status}</span>
          </div>
          <h4 className="text-sm font-semibold leading-relaxed text-foreground">{title}</h4>
        </div>
        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all p-1 rounded-md hover:bg-destructive/10"
          title="Delete"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      {summary && summary !== title && (
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{summary}</p>
      )}
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
        <InfoPill label="Confidence" value={`${confidence}%`} />
        <InfoPill label="Importance" value={`${salience}%`} />
        <InfoPill label="Scope" value={toTitleCase(item.time_scope || 'long_term')} />
        <InfoPill label="Updated" value={updated || 'Recently'} />
      </div>
      <div className="mt-3 text-xs text-muted-foreground">
        Source: <span className="font-medium text-foreground/80">{source}</span>
      </div>
    </div>
  );
}

function EvidenceCard({ item, onDelete }) {
  const sourceType = toTitleCase(item.source_type || 'evidence');
  const created = formatShortDate(item.created_at);
  const session = item.session_id || item.source_ref || 'No session linked';
  const preview = clampText(item.content, 280);

  return (
    <div className="group rounded-2xl border bg-card p-4 shadow-sm transition-colors hover:border-border/70 hover:bg-muted/10">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">{sourceType}</span>
            {created && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">{created}</span>}
          </div>
          <h4 className="text-sm font-semibold text-foreground">{item.filename || item.id || 'Evidence item'}</h4>
        </div>
        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all p-1 rounded-md hover:bg-destructive/10"
          title="Delete"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      {preview && (
        <p className="mt-2 rounded-xl bg-muted/35 px-3 py-2 text-sm leading-relaxed text-muted-foreground">{preview}</p>
      )}
      <div className="mt-3 grid gap-2 text-xs md:grid-cols-2">
        <InfoPill label="Linked source" value={item.source_ref || 'Direct input'} />
        <InfoPill label="Session" value={session} />
      </div>
    </div>
  );
}

function InfoPill({ label, value }) {
  return (
    <div className="rounded-xl bg-muted/35 px-3 py-2">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm font-medium text-foreground">{value}</p>
    </div>
  );
}

// ── Experience Card ─────────────────────────────────────────────

function ExperienceCard({ label, item, onDelete, onEdit }) {
  const [editing, setEditing] = useState(false);
  const name = item.name || 'Company';
  const title = item.title || item.role || '';
  const description = item.description || '';
  const startDate = item.start_date || item.startDate || '';
  const endDate = item.end_date || item.endDate || '';

  const [draft, setDraft] = useState({
    name, title, description, start_date: startDate, end_date: endDate,
  });

  const handleSave = () => {
    // Build only changed properties
    const changes = {};
    if (draft.name !== name) changes.name = draft.name;
    if (draft.title !== title) changes.title = draft.title;
    if (draft.description !== description) changes.description = draft.description;
    if (draft.start_date !== startDate) changes.start_date = draft.start_date;
    if (draft.end_date !== endDate) changes.end_date = draft.end_date;

    if (Object.keys(changes).length > 0) {
      onEdit(label, name, changes);
    }
    setEditing(false);
  };

  const handleCancel = () => {
    setDraft({ name, title, description, start_date: startDate, end_date: endDate });
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="animate-fade-in rounded-2xl border p-4 ring-2 ring-primary/20 shadow-sm">
        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">Company</label>
              <input
                type="text"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
                autoFocus
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">Role / Title</label>
              <input
                type="text"
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">Start Date</label>
              <input
                type="text"
                value={draft.start_date}
                onChange={(e) => setDraft({ ...draft, start_date: e.target.value })}
                placeholder="e.g. Jan 2022"
                className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">End Date</label>
              <input
                type="text"
                value={draft.end_date}
                onChange={(e) => setDraft({ ...draft, end_date: e.target.value })}
                placeholder="Present"
                className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">Description</label>
            <textarea
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              className="w-full rounded-lg border bg-background px-3 py-2 text-sm resize-none h-20 focus:outline-none focus:ring-2 focus:ring-ring/50"
            />
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={handleCancel}
              className="px-3 py-1.5 text-sm font-medium rounded-lg border hover:bg-muted transition-colors flex items-center gap-1.5"
            >
              <X className="h-3.5 w-3.5" /> Cancel
            </button>
            <button
              onClick={handleSave}
              className="px-3 py-1.5 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity flex items-center gap-1.5"
            >
              <Check className="h-3.5 w-3.5" /> Save
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group rounded-2xl border p-4 shadow-sm transition-all hover:bg-muted/20 hover:shadow-md">
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

        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all ml-3 mt-0.5 flex-shrink-0">
          <button
            onClick={() => setEditing(true)}
            className="text-muted-foreground hover:text-foreground p-1 rounded-md hover:bg-accent transition-colors"
            title="Edit"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onDelete}
            className="text-muted-foreground hover:text-destructive p-1 rounded-md hover:bg-destructive/10 transition-colors"
            title="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
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
    <div className="group flex items-center justify-between rounded-xl border border-transparent px-3 py-3 transition-colors hover:border-border/60 hover:bg-muted/25">
      <span className="w-28 flex-shrink-0 text-sm font-medium text-muted-foreground">{label}</span>
      {editing ? (
        <div className="ml-4 flex flex-1 items-center gap-2 animate-fade-in">
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
        <div className="ml-4 flex flex-1 items-center justify-end gap-2">
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
    <div className="py-10 text-center">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-2xl bg-muted">
        <FileText className="h-5 w-5 text-muted-foreground/50" />
      </div>
      <p className="text-sm font-medium text-foreground">Nothing here yet</p>
      <p className="mt-1 text-sm text-muted-foreground">Add information above or upload a document to populate this section.</p>
    </div>
  );
}

// ── Confirmation Dialog ──────────────────────────────────────────

function ConfirmDialog({ open, title, message, onConfirm, onCancel, confirmLabel = 'Delete', variant = 'destructive' }) {
  if (!open) return null;

  const btnClass = variant === 'destructive'
    ? 'bg-destructive text-destructive-foreground'
    : 'bg-primary text-primary-foreground';
  const iconBgClass = variant === 'destructive'
    ? 'bg-destructive/10'
    : 'bg-primary/10';
  const iconColor = variant === 'destructive'
    ? 'text-destructive'
    : 'text-primary';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center animate-fade-in">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onCancel} />
      {/* Dialog */}
      <div className="relative mx-4 w-full max-w-sm rounded-2xl border bg-card p-6 shadow-xl animate-fade-in-up">
        <div className="flex items-start gap-3 mb-4">
          <div className={`w-10 h-10 rounded-full ${iconBgClass} flex items-center justify-center flex-shrink-0`}>
            <AlertTriangle className={`h-5 w-5 ${iconColor}`} />
          </div>
          <div>
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="text-sm text-muted-foreground mt-1">{message}</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium rounded-lg border hover:bg-muted transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={`px-4 py-2 text-sm font-medium rounded-lg ${btnClass} hover:opacity-90 transition-opacity`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
