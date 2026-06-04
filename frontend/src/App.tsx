import { useState, useRef, useEffect } from 'react';
import { 
  Users, 
  FileSpreadsheet, 
  Settings, 
  Upload, 
  Plus, 
  Search, 
  Sparkles, 
  Mail, 
  BookOpen, 
  Briefcase, 
  CheckCircle2, 
  XCircle, 
  ChevronRight, 
  X, 
  Loader2, 
  ShieldCheck, 
  Check,
  FolderOpen,
  FolderPlus,
  FileText,
  ExternalLink,
  Trash2
} from 'lucide-react';
import axios from 'axios';
import './App.css';

// Custom inline SVG for Github to avoid Lucide package mismatch
const GithubIcon = ({ size = 20, ...props }: { size?: number; [key: string]: any }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    {...props}
  >
    <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
    <path d="M9 18c-4.51 2-5-2-7-2" />
  </svg>
);

// TypeScript Interfaces for candidate state
interface Education {
  institution: string;
  degree: string;
  gpa: string;
  duration: string;
}

interface Experience {
  company: string;
  role: string;
  duration: string;
  description: string;
}

interface Project {
  title: string;
  description: string;
  technologies: string[];
}

interface RecentRepo {
  name: string;
  languages: string[];
  stars: number;
  last_active: string;
}

interface GitHubData {
  name: string;
  total_public_repositories: number;
  account_created: string;
  bio: string;
  recent_projects: RecentRepo[];
}

interface Candidate {
  id: string;
  job_id: string; // Associated Job Role Folder ID
  name: string;
  github_username: string;
  email: string;
  phone: string;
  category: string;
  education: Education[];
  experience: Experience[];
  projects: Project[];
  skills: string[];
  certifications: string[];
  miscellaneous_details: string;
  github_data: GitHubData | null;
  project_verification: string;
  score: number;
  reasoning: string;
  ats_reasoning_summary?: string;
  jd_score: number;
  jd_reasoning: string;
  jd_reasoning_summary?: string;
  final_weighted_score: number;
  final_decision: string;
  candidate_email: string;
  hiring_manager_brief: string;
  interview_questions: string[];
  resume_filename?: string;
  resume_gcs_uri?: string;
}

interface Job {
  _id: string;
  name: string;
  jd_filename: string | null;
  jd_text: string | null;
  skills?: { name: string; weight: number }[];
  required_graduation_years?: number[];
  minimum_gpa?: number | null;
  other_eligibility_criteria?: string | null;
}

const INITIAL_CANDIDATES: Candidate[] = [];

const CircularProgress = ({ 
  score, 
  size = 100, 
  strokeWidth = 8, 
  color = "#7C3AED", 
  label = "" 
}: { 
  score: number; 
  size?: number; 
  strokeWidth?: number; 
  color?: string; 
  label?: string 
}) => {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (Math.min(100, Math.max(0, score)) / 100) * circumference;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', position: 'relative', width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)', width: size, height: size }}>
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="transparent"
          stroke="var(--border-color)"
          strokeWidth={strokeWidth}
        />
        {/* Foreground circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="transparent"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 0.6s cubic-bezier(0.4, 0, 0.2, 1)' }}
        />
      </svg>
      <div style={{ position: 'absolute', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
        <span style={{ fontSize: size * 0.24, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.1 }}>
          {score}
        </span>
        {label && (
          <span style={{ fontSize: size * 0.09, textTransform: 'uppercase', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.5px', marginTop: '2px' }}>
            {label}
          </span>
        )}
      </div>
    </div>
  );
};

function App() {
  const [candidates, setCandidates] = useState<Candidate[]>(INITIAL_CANDIDATES);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>("1");
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  
  // Job Role (Folders) States
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string>(() => {
    return localStorage.getItem("selectedJobId") || "";
  });
  const [isCreateJobOpen, setIsCreateJobOpen] = useState(false);
  const [jobToDeleteId, setJobToDeleteId] = useState<string | null>(null);
  const [evaluationWizardStep, setEvaluationWizardStep] = useState<0 | 1>(0);
  const [newJobName, setNewJobName] = useState("");
  const [isUploadingJd, setIsUploadingJd] = useState(false);
  const jdFileInputRef = useRef<HTMLInputElement>(null);

  // Skill Weight Config States
  const [isSkillsModalOpen, setIsSkillsModalOpen] = useState(false);
  const [editingSkills, setEditingSkills] = useState<{ name: string; weight: number }[]>([]);
  const [editingGradYears, setEditingGradYears] = useState<string>("");
  const [editingMinGpa, setEditingMinGpa] = useState<string>("");
  const [editingOtherCriteria, setEditingOtherCriteria] = useState<string>("");
  const [skillsSaveError, setSkillsSaveError] = useState<string | null>(null);
  const [isSavingSkills, setIsSavingSkills] = useState(false);
  const [isInlineSetupSaved, setIsInlineSetupSaved] = useState(false);

  // Sidebar Navigation State
  const [activeSidebarTab, setActiveSidebarTab] = useState<string>("dashboard");

  // Filter and Search States
  const [searchQuery, setSearchQuery] = useState("");
  const [filterDecision, setFilterDecision] = useState<"all" | "inprogress" | "shortlisted" | "selected" | "rejected">("all");

  // Detail Drawer Active Tab
  const [activeDrawerTab, setActiveDrawerTab] = useState<"brief" | "profile" | "questions" | "github">("brief");

  // Candidate Resume Upload State
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStep, setUploadStep] = useState(0);
  const [apiError, setApiError] = useState<string | null>(null);

  const resumeInputRef = useRef<HTMLInputElement>(null);



  // Save selected job ID to localStorage on change
  useEffect(() => {
    if (selectedJobId) {
      localStorage.setItem("selectedJobId", selectedJobId);
    } else {
      localStorage.removeItem("selectedJobId");
    }
  }, [selectedJobId]);

  // Synchronize setup state when job is changed
  useEffect(() => {
    if (selectedJobId) {
      const selectedJob = jobs.find(j => j._id === selectedJobId);
      const jobCandCount = candidates.filter(c => c.job_id === selectedJobId).length;
      
      if (jobCandCount > 0) {
        setIsInlineSetupSaved(true);
      } else if (selectedJob && selectedJob.jd_filename) {
        if (selectedJob.skills && selectedJob.skills.length > 0) {
          setIsInlineSetupSaved(true);
        } else {
          setIsInlineSetupSaved(false);
        }
      } else {
        setIsInlineSetupSaved(false);
      }
    }
  }, [selectedJobId, jobs, candidates]);

  // Fetch jobs and candidates on mount
  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        const jobsResponse = await axios.get("http://127.0.0.1:8000/api/jobs");
        if (jobsResponse.data && jobsResponse.data.jobs) {
          setJobs(jobsResponse.data.jobs);
          if (jobsResponse.data.jobs.length > 0) {
            const savedJobId = localStorage.getItem("selectedJobId");
            const jobExists = jobsResponse.data.jobs.some((j: any) => j._id === savedJobId);
            if (savedJobId && jobExists) {
              setSelectedJobId(savedJobId);
            } else {
              setSelectedJobId(jobsResponse.data.jobs[0]._id);
            }
          }
        }

        const candidatesResponse = await axios.get("http://127.0.0.1:8000/api/candidates");
        if (candidatesResponse.data && candidatesResponse.data.candidates) {
          const mapped: Candidate[] = candidatesResponse.data.candidates.map((c: any) => {
            let decision = c.final_decision?.toLowerCase() || "rejected";
            if (decision === "approved") {
              decision = "shortlisted";
            }
            return {
              ...c,
              id: c._id || c.id,
              final_decision: decision
            };
          });
          setCandidates(mapped);
        }
      } catch (err) {
        console.error("Failed to load initial database entries:", err);
      }
    };
    fetchInitialData();
  }, []);

  const selectedJob = jobs.find(j => j._id === selectedJobId);
  const selectedCandidate = candidates.find(c => c.id === selectedCandidateId);

  // Steps for the pipeline spinner loader
  const PIPELINE_STEPS = [
    "Extracting document text contents (PDF/DOCX)...",
    "Querying GitHub API & checking public repositories...",
    "Calculating candidate score weights via ATS Matrix...",
    "Generating final decision, briefs, and interview queries..."
  ];

  // Simulate evaluation step progression while Axios calls the backend API
  useEffect(() => {
    let interval: any;
    if (isUploading) {
      interval = setInterval(() => {
        setUploadStep((prev) => {
          if (prev < 3) {
            return prev + 1;
          }
          return prev;
        });
      }, 3000);
    } else {
      setUploadStep(0);
    }
    return () => clearInterval(interval);
  }, [isUploading]);

  // Compute folder-specific metrics
  const activeCandidates = candidates.filter(c => c.job_id === selectedJobId);
  const totalProcessed = activeCandidates.length;
  const shortlistedOrSelectedCount = activeCandidates.filter(c => c.final_decision === "selected" || c.final_decision === "shortlisted").length;
  const avgMatchScore = activeCandidates.length > 0 
    ? Math.ceil(activeCandidates.reduce((sum, c) => sum + c.final_weighted_score, 0) / activeCandidates.length)
    : 0;

  // Handle Drag & Drop events
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDropResume = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setResumeFile(e.dataTransfer.files[0]);
    }
  };

  // Create a new job role folder
  const handleCreateJobFolder = async () => {
    if (!newJobName.trim()) return;
    try {
      const response = await axios.post("http://127.0.0.1:8000/api/jobs", {
        name: newJobName
      });
      const newJob = response.data;
      setJobs((prev) => [...prev, newJob]);
      setSelectedJobId(newJob._id);
      setNewJobName("");
      setIsCreateJobOpen(false);
    } catch (err) {
      console.error("Failed to create job folder:", err);
    }
  };

  // Delete an existing job role folder and its candidate evaluations
  const handleDeleteJob = async (jobId: string) => {
    try {
      await axios.delete(`http://127.0.0.1:8000/api/job/${jobId}`);
      
      const updatedJobs = jobs.filter(j => j._id !== jobId);
      setJobs(updatedJobs);
      
      // Filter out deleted job's candidates from state
      setCandidates(prev => prev.filter(c => c.job_id !== jobId));
      
      // Select first remaining job if available, otherwise clear selection
      if (updatedJobs.length > 0) {
        setSelectedJobId(updatedJobs[0]._id);
      } else {
        setSelectedJobId("");
      }
      
      // Clear drawer selection
      setSelectedCandidateId("");
    } catch (err) {
      console.error("Failed to delete job:", err);
      alert("Failed to delete job. Please verify the backend is running and try again.");
    }
  };

  // Upload Job Description (JD) for the active Job Role folder
  const handleJdUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || !e.target.files[0] || !selectedJobId) return;
    const file = e.target.files[0];
    
    setIsUploadingJd(true);
    const formData = new FormData();
    formData.append("jd", file);

    try {
      await axios.post(`http://127.0.0.1:8000/api/jobs/${selectedJobId}/jd`, formData, {
        headers: {
          "Content-Type": "multipart/form-data"
        }
      });
      
      setJobs((prev) => prev.map((j) => {
        if (j._id === selectedJobId) {
          return { ...j, jd_filename: file.name };
        }
        return j;
      }));
      
      // Force page refresh of this selected job values
      const updatedJobs = await axios.get("http://127.0.0.1:8000/api/jobs");
      if (updatedJobs.data && updatedJobs.data.jobs) {
        setJobs(updatedJobs.data.jobs);
        
        // Find the newly updated job
        const updatedJob = updatedJobs.data.jobs.find((j: any) => j._id === selectedJobId);
        if (updatedJob) {
          // Pre-populate and show inline setup
          setEditingSkills(updatedJob.skills || []);
          setEditingGradYears(updatedJob.required_graduation_years?.join(", ") || "");
          setEditingMinGpa(updatedJob.minimum_gpa !== undefined && updatedJob.minimum_gpa !== null ? String(updatedJob.minimum_gpa) : "");
          setEditingOtherCriteria(updatedJob.other_eligibility_criteria || "");
          setSkillsSaveError(null);
          setIsInlineSetupSaved(false); // Transition to inline weights config pane
        }
      }
    } catch (err) {
      console.error("Failed to upload JD:", err);
    } finally {
      setIsUploadingJd(false);
    }
  };

  // Skill Config Helpers
  const updateSkillWeight = (index: number, newWeight: number) => {
    setEditingSkills(prev => prev.map((s, i) => i === index ? { ...s, weight: newWeight } : s));
  };

  const updateSkillName = (index: number, newName: string) => {
    setEditingSkills(prev => prev.map((s, i) => i === index ? { ...s, name: newName } : s));
  };

  const deleteSkill = (index: number) => {
    setEditingSkills(prev => prev.filter((_, i) => i !== index));
  };

  const addSkill = () => {
    setEditingSkills(prev => [...prev, { name: "New Skill", weight: 0 }]);
  };

  const saveSkills = async () => {
    const total = editingSkills.reduce((sum, s) => sum + s.weight, 0);
    if (total !== 100) {
      setSkillsSaveError("Total weight must be exactly 100%.");
      return;
    }

    const gradYearsArray = editingGradYears
      .split(",")
      .map(y => parseInt(y.trim()))
      .filter(y => !isNaN(y));

    const minGpaValue = editingMinGpa.trim() === "" ? null : parseFloat(editingMinGpa.trim());
    if (editingMinGpa.trim() !== "" && isNaN(minGpaValue as number)) {
      setSkillsSaveError("Minimum GPA must be a valid number or empty.");
      return;
    }

    setIsSavingSkills(true);
    setSkillsSaveError(null);
    try {
      await axios.put(`http://127.0.0.1:8000/api/jobs/${selectedJobId}/skills`, {
        skills: editingSkills,
        required_graduation_years: gradYearsArray,
        minimum_gpa: minGpaValue,
        other_eligibility_criteria: editingOtherCriteria.trim() || null
      });
      setJobs(prev => prev.map(j => {
        if (j._id === selectedJobId) {
          return { 
            ...j, 
            skills: editingSkills,
            required_graduation_years: gradYearsArray,
            minimum_gpa: minGpaValue,
            other_eligibility_criteria: editingOtherCriteria.trim() || null
          };
        }
        return j;
      }));

      // Refetch updated candidates to display new scores in UI
      const candidatesResponse = await axios.get("http://127.0.0.1:8000/api/candidates");
      if (candidatesResponse.data && candidatesResponse.data.candidates) {
        const mapped: Candidate[] = candidatesResponse.data.candidates.map((c: any) => {
          let decision = c.final_decision?.toLowerCase() || "rejected";
          if (decision === "approved") {
            decision = "shortlisted";
          }
          return {
            ...c,
            id: c._id || c.id,
            final_decision: decision
          };
        });
        setCandidates(mapped);
      }

      setIsSkillsModalOpen(false);
    } catch (err: any) {
      console.error(err);
      setSkillsSaveError(err.response?.data?.detail || "Failed to save skill weights.");
    } finally {
      setIsSavingSkills(false);
    }
  };

  // Save configured criteria and trigger evaluation pipeline
  const saveCriteriaAndTriggerEvaluation = async () => {
    // 1. Validate weights first
    const total = editingSkills.reduce((sum, s) => sum + s.weight, 0);
    if (total !== 100) {
      setApiError("Total skill weights must sum to exactly 100% to run evaluation.");
      return;
    }

    const gradYearsArray = editingGradYears
      .split(",")
      .map(y => parseInt(y.trim()))
      .filter(y => !isNaN(y));

    const minGpaValue = editingMinGpa.trim() === "" ? null : parseFloat(editingMinGpa.trim());
    if (editingMinGpa.trim() !== "" && isNaN(minGpaValue as number)) {
      setApiError("Minimum GPA must be a valid number or empty.");
      return;
    }

    setApiError(null);
    setIsUploading(true);
    setUploadStep(0);
    
    try {
      // 2. Save configured parameters to the database
      await axios.put(`http://127.0.0.1:8000/api/jobs/${selectedJobId}/skills`, {
        skills: editingSkills,
        required_graduation_years: gradYearsArray,
        minimum_gpa: minGpaValue,
        other_eligibility_criteria: editingOtherCriteria.trim() || null
      });

      // 3. Update the frontend jobs state in-memory so it stays synchronized
      setJobs(prev => prev.map(j => {
        if (j._id === selectedJobId) {
          return { 
            ...j, 
            skills: editingSkills,
            required_graduation_years: gradYearsArray,
            minimum_gpa: minGpaValue,
            other_eligibility_criteria: editingOtherCriteria.trim() || null
          };
        }
        return j;
      }));

      // 4. Trigger evaluation API
      await triggerEvaluation();
    } catch (err: any) {
      console.error(err);
      setApiError(err.response?.data?.detail || "Failed to save weights and trigger evaluation.");
      setIsUploading(false);
    }
  };

  const handleSaveWeightsOnly = async () => {
    // 1. Validate weights first
    const total = editingSkills.reduce((sum, s) => sum + s.weight, 0);
    if (total !== 100) {
      setSkillsSaveError("Total skill weights must sum to exactly 100% to save.");
      return;
    }

    const gradYearsArray = editingGradYears
      .split(",")
      .map(y => parseInt(y.trim()))
      .filter(y => !isNaN(y));

    const minGpaValue = editingMinGpa.trim() === "" ? null : parseFloat(editingMinGpa.trim());
    if (editingMinGpa.trim() !== "" && isNaN(minGpaValue as number)) {
      setSkillsSaveError("Minimum GPA must be a valid number or empty.");
      return;
    }

    setSkillsSaveError(null);
    setIsSavingSkills(true);
    
    try {
      // 2. Save configured parameters to the database
      await axios.put(`http://127.0.0.1:8000/api/jobs/${selectedJobId}/skills`, {
        skills: editingSkills,
        required_graduation_years: gradYearsArray,
        minimum_gpa: minGpaValue,
        other_eligibility_criteria: editingOtherCriteria.trim() || null
      });

      // 3. Update the frontend jobs state in-memory so it stays synchronized
      setJobs(prev => prev.map(j => {
        if (j._id === selectedJobId) {
          return { 
            ...j, 
            skills: editingSkills,
            required_graduation_years: gradYearsArray,
            minimum_gpa: minGpaValue,
            other_eligibility_criteria: editingOtherCriteria.trim() || null
          };
        }
        return j;
      }));

      setIsInlineSetupSaved(true);
    } catch (err: any) {
      console.error(err);
      setSkillsSaveError(err.response?.data?.detail || "Failed to save skill weights.");
    } finally {
      setIsSavingSkills(false);
    }
  };

  // Run the evaluate API call for a specific job folder context
  const triggerEvaluation = async () => {
    if (!resumeFile || !selectedJobId) {
      setApiError("Please select a candidate resume and make sure you are inside a job folder.");
      return;
    }

    setApiError(null);
    setIsUploading(true);
    setUploadStep(0);

    const formData = new FormData();
    formData.append("resume", resumeFile);

    try {
      // POST to job-specific evaluate endpoint
      const response = await axios.post(`http://127.0.0.1:8000/api/jobs/${selectedJobId}/evaluate`, formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      const data = response.data;

      // Map API response to Candidate interface
      const newCandidate: Candidate = {
        id: data._id || Date.now().toString(),
        job_id: selectedJobId,
        name: data.name || resumeFile.name.replace(/\.[^/.]+$/, "").toUpperCase(),
        github_username: data.github_username || "N/A",
        email: data.email || "N/A",
        phone: data.phone || "N/A",
        category: data.category || "General",
        education: data.education || [],
        experience: data.experience || [],
        projects: data.projects || [],
        skills: data.skills || [],
        certifications: data.certifications || [],
        miscellaneous_details: data.miscellaneous_details || "N/A",
        github_data: data.github_data || null,
        project_verification: data.project_verification || "No verification logs.",
        score: data.score || 0,
        reasoning: data.reasoning || "",
        ats_reasoning_summary: data.ats_reasoning_summary || "",
        jd_score: data.jd_score || 0,
        jd_reasoning: data.jd_reasoning || "",
        jd_reasoning_summary: data.jd_reasoning_summary || "",
        final_weighted_score: data.final_weighted_score || 0,
        final_decision: data.final_decision?.toLowerCase() === "approved" ? "shortlisted" : (data.final_decision?.toLowerCase() || "rejected"),
        candidate_email: data.candidate_email || "",
        hiring_manager_brief: data.hiring_manager_brief || "",
        interview_questions: data.interview_questions || [],
        resume_filename: data.resume_filename,
        resume_gcs_uri: data.resume_gcs_uri
      };

      setCandidates((prev) => [newCandidate, ...prev]);
      setSelectedCandidateId(newCandidate.id);
      setIsUploadOpen(false);
      setResumeFile(null);
    } catch (err: any) {
      console.error(err);
      setApiError(err.response?.data?.detail || "Connection failed. Please ensure the backend server is running on port 8000.");
    } finally {
      setIsUploading(false);
    }
  };

  // Custom markdown-to-HTML parser
  const renderMarkdown = (text: string) => {
    if (!text) return null;
    return text.split('\n').map((line, idx) => {
      if (line.startsWith('### ')) {
        return <h4 key={idx} className="markdown-h4" style={{ color: 'var(--text-primary)', marginTop: '12px', marginBottom: '6px', fontSize: '13.5px', fontWeight: 600 }}>{line.replace('### ', '')}</h4>;
      }
      if (line.startsWith('## ')) {
        return <h3 key={idx} className="markdown-h3" style={{ color: 'var(--color-accent)', marginTop: '16px', marginBottom: '8px', fontSize: '14.5px', fontWeight: 600, borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>{line.replace('## ', '')}</h3>;
      }
      if (line.startsWith('# ')) {
        return <h2 key={idx} className="markdown-h2" style={{ color: 'var(--color-accent)', marginTop: '20px', marginBottom: '10px', fontSize: '16px', fontWeight: 700 }}>{line.replace('# ', '')}</h2>;
      }
      if (line.trim().startsWith('* ') || line.trim().startsWith('- ')) {
        const content = line.trim().replace(/^[*+-]\s+/, '');
        return (
          <ul key={idx} style={{ margin: '4px 0', paddingLeft: '16px', color: 'var(--text-primary)' }}>
            <li style={{ fontSize: '13px', lineHeight: '1.4' }}>{parseInlineMarkdown(content)}</li>
          </ul>
        );
      }
      if (line.trim() === '') {
        return <div key={idx} style={{ height: '8px' }} />;
      }
      return <p key={idx} style={{ margin: '6px 0', fontSize: '13px', lineHeight: 1.5, color: 'var(--text-primary)' }}>{parseInlineMarkdown(line)}</p>;
    });
  };

  const parseInlineMarkdown = (inlineText: string) => {
    const boldRegex = /\*\*(.*?)\*\*/g;
    const parts = [];
    let lastIndex = 0;
    let match;
    
    while ((match = boldRegex.exec(inlineText)) !== null) {
      if (match.index > lastIndex) {
        parts.push(inlineText.substring(lastIndex, match.index));
      }
      parts.push(<strong key={match.index} style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{match[1]}</strong>);
      lastIndex = boldRegex.lastIndex;
    }
    
    if (lastIndex < inlineText.length) {
      parts.push(inlineText.substring(lastIndex));
    }
    
    return parts.length > 0 ? parts : inlineText;
  };

  // Filter candidates list based on selected job, search, and decision filters
  const filteredCandidates = candidates
    .filter((c) => {
      const matchesJob = c.job_id === selectedJobId;
      const matchesSearch = c.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                            c.skills.some(s => s.toLowerCase().includes(searchQuery.toLowerCase())) ||
                            c.github_username.toLowerCase().includes(searchQuery.toLowerCase());
      
      const matchesFilter = filterDecision === "all" || c.final_decision === filterDecision;
      return matchesJob && matchesSearch && matchesFilter;
    })
    .sort((a, b) => b.final_weighted_score - a.final_weighted_score);

  return (
    <div className="dashboard-container">
      {/* Sidebar Panel */}
      <aside className="sidebar">
        <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '20px', flex: 1, minHeight: 0 }}>
          <div className="logo-container" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '0 8px' }}>
            <Sparkles size={24} />
            <span style={{ fontSize: '15px', fontWeight: 700, letterSpacing: '-0.3px', color: '#FFFFFF' }}>AI ATS Portal</span>
          </div>

          <div className="folders-header" style={{ padding: '0 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', boxSizing: 'border-box' }}>
            <h3 style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.8px', color: 'rgba(255, 255, 255, 0.4)', margin: 0, fontWeight: 700 }}>Job Folders</h3>
            <button 
              type="button" 
              className="create-folder-btn"
              style={{ 
                width: '24px', 
                height: '24px', 
                borderRadius: '6px', 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'center', 
                backgroundColor: 'rgba(255, 255, 255, 0.06)', 
                border: 'none', 
                color: '#FFFFFF', 
                cursor: 'pointer' 
              }}
              title="Create Job Role"
              onClick={() => setIsCreateJobOpen(true)}
            >
              <Plus size={14} />
            </button>
          </div>

          <div className="folders-list" style={{ padding: '0 4px', display: 'flex', flexDirection: 'column', gap: '8px', overflowY: 'auto', flex: 1, width: '100%', boxSizing: 'border-box' }}>
            {jobs.map((job) => {
              const jobCandCount = candidates.filter(c => c.job_id === job._id).length;
              const isActive = selectedJobId === job._id && activeSidebarTab !== "settings";
              return (
                <div 
                  key={job._id}
                  className={`folder-item ${isActive ? 'active' : ''}`}
                  onClick={() => {
                    setSelectedJobId(job._id);
                    setSelectedCandidateId(""); // Clear drawer selection when toggling jobs
                    setActiveSidebarTab("dashboard");
                  }}
                >
                  <div className="folder-name-row">
                    <span className="folder-name">{job.name}</span>
                    {job.jd_filename ? (
                      <span className="folder-badge has-jd" title="Job Description Uploaded">JD</span>
                    ) : (
                      <span className="folder-badge no-jd" title="No JD Uploaded">No JD</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '2px' }}>
                    <span className="folder-candidates-count">{jobCandCount} applicants</span>
                  </div>
                  {job.jd_filename && (
                    <span className="folder-jd-filename" title={job.jd_filename}>
                      📄 {job.jd_filename}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="sidebar-footer" style={{ width: '100%', borderTop: '1px solid rgba(255, 255, 255, 0.08)', paddingTop: '12px', paddingLeft: '8px', paddingRight: '8px', boxSizing: 'border-box' }}>
          <div 
            className={`nav-item ${activeSidebarTab === "settings" ? "active" : ""}`}
            style={{ width: '100%', gap: '10px', justifyContent: 'flex-start', padding: '0 12px', boxSizing: 'border-box', height: '40px', borderRadius: '8px' }}
            title="Settings"
            onClick={() => {
              setActiveSidebarTab("settings");
              setSelectedJobId("");
            }}
          >
            <Settings size={18} style={{ flexShrink: 0 }} />
            <span style={{ fontSize: '13px', fontWeight: 500 }}>Settings</span>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      {activeSidebarTab === "dashboard" ? (
        <main className="main-content">
          {/* Header */}
          <header className="dashboard-header">
            <div className="header-title-section">
              <h1>AI ATS Candidate Evaluator</h1>
              <p>Evaluate resume compliance and audit candidate GitHub code authenticity in real-time.</p>
            </div>
            <div className="header-actions">
              <div className="admin-profile">
                <div className="admin-avatar">
                  <Users size={14} />
                </div>
                <span>Recruiter Portal</span>
              </div>
            </div>
          </header>

          <div className="dashboard-layout-with-folders">
            {/* Folder Main Content Section */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '20px', minWidth: 0 }}>
              {selectedJob ? (
                <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <FolderOpen size={24} style={{ color: 'var(--color-accent)' }} />
                      <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 600 }}>{selectedJob.name}</h2>
                    </div>

                    <div style={{ display: 'flex', gap: '12px' }}>
                      {selectedJob.jd_filename && (
                        <>
                          <input 
                            type="file"
                            ref={jdFileInputRef}
                            style={{ display: 'none' }}
                            accept=".pdf,.docx"
                            onChange={handleJdUpload}
                          />
                          <button 
                            type="button" 
                            className="btn-secondary"
                            style={{ padding: '8px 14px', display: 'flex', alignItems: 'center', gap: '6px' }}
                            onClick={() => {
                              setEditingSkills(selectedJob.skills || []);
                              setEditingGradYears(selectedJob.required_graduation_years?.join(", ") || "");
                              setEditingMinGpa(selectedJob.minimum_gpa !== undefined && selectedJob.minimum_gpa !== null ? String(selectedJob.minimum_gpa) : "");
                              setEditingOtherCriteria(selectedJob.other_eligibility_criteria || "");
                              setSkillsSaveError(null);
                              setIsSkillsModalOpen(true);
                            }}
                          >
                            <Settings size={14} />
                            Configure Weights
                          </button>
                          <button 
                            type="button" 
                            className="btn-secondary"
                            style={{ padding: '8px 14px' }}
                            onClick={() => jdFileInputRef.current?.click()}
                          >
                            Update JD
                          </button>
                          <button 
                            type="button" 
                            className="btn-primary" 
                            onClick={() => {
                              setEditingSkills(selectedJob.skills || []);
                              setEditingGradYears(selectedJob.required_graduation_years?.join(", ") || "");
                              setEditingMinGpa(selectedJob.minimum_gpa !== undefined && selectedJob.minimum_gpa !== null ? String(selectedJob.minimum_gpa) : "");
                              setEditingOtherCriteria(selectedJob.other_eligibility_criteria || "");
                              setEvaluationWizardStep(0);
                              setApiError(null);
                              setResumeFile(null);
                              setIsUploadOpen(true);
                            }}
                          >
                            <Plus size={16} />
                            Evaluate Candidate
                          </button>
                        </>
                      )}
                      <button 
                        type="button" 
                        className="btn-danger"
                        style={{ padding: '8px 14px', display: 'flex', alignItems: 'center', gap: '6px' }}
                        onClick={() => setJobToDeleteId(selectedJob._id)}
                      >
                        <Trash2 size={14} />
                        Delete Job
                      </button>
                    </div>
                  </div>

                  {!selectedJob.jd_filename ? (
                    /* JD Upload Empty State Dropzone */
                    <div 
                      style={{ 
                        flex: 1, 
                        display: 'flex', 
                        flexDirection: 'column', 
                        alignItems: 'center', 
                        justifyContent: 'center',
                        border: '2px dashed var(--border-hover)',
                        backgroundColor: 'var(--bg-card)',
                        borderRadius: '16px',
                        padding: '40px',
                        textAlign: 'center',
                        gap: '16px'
                      }}
                    >
                      <FolderPlus size={48} style={{ color: 'var(--text-muted)' }} />
                      <div>
                        <h3 style={{ margin: '0 0 4px', fontSize: '18px' }}>No Job Description (JD) Configured</h3>
                        <p style={{ margin: 0, fontSize: '14px', color: 'var(--text-secondary)' }}>
                          Upload the job description specification file to activate this job folder.
                        </p>
                      </div>
                      
                      <input 
                        type="file"
                        ref={jdFileInputRef}
                        style={{ display: 'none' }}
                        accept=".pdf,.docx"
                        onChange={handleJdUpload}
                      />
                      <button 
                        type="button" 
                        className="btn-primary"
                        disabled={isUploadingJd}
                        onClick={() => jdFileInputRef.current?.click()}
                      >
                        {isUploadingJd ? (
                          <>
                            <Loader2 className="spinner-icon" size={14} />
                            Uploading & Parsing...
                          </>
                        ) : (
                          <>
                            <Upload size={14} />
                            Upload JD File (PDF/DOCX)
                          </>
                        )}
                      </button>
                    </div>
                  ) : totalProcessed === 0 && !isInlineSetupSaved ? (
                    /* Inline Weights & Criteria Setup View */
                    <div className="inline-setup-container" style={{
                      backgroundColor: 'var(--bg-card)',
                      border: '1px solid var(--border-color)',
                      borderRadius: '16px',
                      padding: '30px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '24px'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '16px' }}>
                        <div>
                          <h3 style={{ margin: '0 0 4px', fontSize: '18px', fontWeight: 600 }}>Configure Screening & Selection Criteria</h3>
                          <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)' }}>
                            Review and adjust the extracted skills, weights, and pre-screening criteria for this job.
                          </p>
                        </div>
                        <button 
                          type="button" 
                          className="btn-secondary" 
                          style={{ padding: '8px 14px' }}
                          onClick={() => jdFileInputRef.current?.click()}
                        >
                          Change JD File
                        </button>
                      </div>

                      {skillsSaveError && (
                        <div style={{ backgroundColor: 'var(--color-error-bg)', border: '1px solid var(--color-error-border)', color: 'var(--color-error)', padding: '12px 16px', borderRadius: '10px', fontSize: '13px' }}>
                          {skillsSaveError}
                        </div>
                      )}

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                        {/* Skills Section */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                          <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-secondary)', margin: '0' }}>Skill Weights (Must sum to 100%)</h4>
                          {editingSkills.length === 0 ? (
                            <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)', fontSize: '13px', border: '1px dashed var(--border-color)', borderRadius: '8px' }}>
                              No skills configured. Click "Add Custom Skill" below to define skills.
                            </div>
                          ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                              {editingSkills.map((skill, index) => (
                                <div key={index} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 14px', backgroundColor: 'var(--bg-card-hover)', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                                  <input 
                                    type="text" 
                                    style={{
                                      flex: '1.2',
                                      padding: '6px 10px',
                                      border: '1px solid var(--border-color)',
                                      borderRadius: '6px',
                                      fontSize: '13px',
                                      color: 'var(--text-primary)',
                                      backgroundColor: '#FFFFFF',
                                      minWidth: '100px'
                                    }}
                                    value={skill.name}
                                    onChange={(e) => updateSkillName(index, e.target.value)}
                                    placeholder="Skill Name"
                                  />
                                  
                                  <div style={{ flex: '2', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <input 
                                      type="range" 
                                      min="0" 
                                      max="100" 
                                      style={{
                                        flex: 1,
                                        cursor: 'pointer',
                                        accentColor: 'var(--color-accent)'
                                      }}
                                      value={skill.weight}
                                      onChange={(e) => updateSkillWeight(index, parseInt(e.target.value))}
                                    />
                                    <span style={{ fontSize: '13px', fontWeight: 600, minWidth: '40px', textAlign: 'right', color: 'var(--text-primary)' }}>
                                      {skill.weight}%
                                    </span>
                                  </div>

                                  <button 
                                    type="button"
                                    style={{
                                      padding: '6px',
                                      borderRadius: '6px',
                                      border: 'none',
                                      backgroundColor: 'transparent',
                                      color: 'var(--text-muted)',
                                      cursor: 'pointer',
                                      display: 'flex',
                                      alignItems: 'center',
                                      justifyContent: 'center'
                                    }}
                                    onClick={() => deleteSkill(index)}
                                    title="Delete Skill"
                                  >
                                    <X size={16} />
                                  </button>
                                </div>
                              ))}
                            </div>
                          )}
                          
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
                            <button 
                              type="button"
                              className="btn-secondary"
                              style={{ padding: '6px 12px', fontSize: '13px' }}
                              onClick={addSkill}
                            >
                              <Plus size={14} />
                              Add Custom Skill
                            </button>

                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                              <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                                Total Weight:
                              </span>
                              <span 
                                style={{ 
                                  fontSize: '15px', 
                                  fontWeight: 700, 
                                  color: editingSkills.reduce((sum, s) => sum + s.weight, 0) === 100 ? 'var(--color-success)' : 'var(--color-error)' 
                                }}
                              >
                                {editingSkills.reduce((sum, s) => sum + s.weight, 0)}%
                              </span>
                            </div>
                          </div>
                        </div>

                        {/* Pre-Screening Section */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
                          <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-secondary)', margin: '0' }}>Pre-Screening Eligibility Criteria</h4>
                          
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                              <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>Graduation Years (comma separated)</label>
                              <input 
                                type="text" 
                                placeholder="e.g. 2025, 2026"
                                style={{
                                  padding: '8px 12px',
                                  border: '1px solid var(--border-color)',
                                  borderRadius: '6px',
                                  fontSize: '13px',
                                  color: 'var(--text-primary)',
                                  backgroundColor: '#FFFFFF',
                                }}
                                value={editingGradYears}
                                onChange={(e) => setEditingGradYears(e.target.value)}
                              />
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                              <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>Minimum GPA</label>
                              <input 
                                type="text" 
                                placeholder="e.g. 3.0"
                                style={{
                                  padding: '8px 12px',
                                  border: '1px solid var(--border-color)',
                                  borderRadius: '6px',
                                  fontSize: '13px',
                                  color: 'var(--text-primary)',
                                  backgroundColor: '#FFFFFF',
                                }}
                                value={editingMinGpa}
                                onChange={(e) => setEditingMinGpa(e.target.value)}
                              />
                            </div>
                          </div>

                          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>Other Eligibility requirements (work authorization, etc.)</label>
                            <textarea 
                              placeholder="e.g. Must be currently authorized to work in the US without visa sponsorship."
                              style={{
                                padding: '8px 12px',
                                border: '1px solid var(--border-color)',
                                borderRadius: '6px',
                                fontSize: '13px',
                                color: 'var(--text-primary)',
                                backgroundColor: '#FFFFFF',
                                resize: 'vertical',
                                height: '60px',
                                fontFamily: 'inherit'
                              }}
                              value={editingOtherCriteria}
                              onChange={(e) => setEditingOtherCriteria(e.target.value)}
                            />
                          </div>
                        </div>
                      </div>

                      <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '12px', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
                        <button 
                          type="button" 
                          className="btn-primary" 
                          disabled={isSavingSkills || editingSkills.reduce((sum, s) => sum + s.weight, 0) !== 100}
                          onClick={handleSaveWeightsOnly}
                          style={{ padding: '10px 20px', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}
                        >
                          {isSavingSkills ? (
                            <>
                              <Loader2 className="spinner-icon" size={16} />
                              Saving Setup...
                            </>
                          ) : (
                            <>
                              <Check size={16} />
                              Save Weights & Setup Job
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  ) : totalProcessed === 0 && isInlineSetupSaved ? (
                    /* Inline Resume Upload Landing Page View */
                    <div style={{
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      border: '2px dashed var(--border-hover)',
                      backgroundColor: 'var(--bg-card)',
                      borderRadius: '16px',
                      padding: '50px 40px',
                      textAlign: 'center',
                      gap: '20px'
                    }}>
                      <div style={{
                        width: '64px',
                        height: '64px',
                        borderRadius: '50%',
                        backgroundColor: 'var(--color-success-bg)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'var(--color-success)',
                        marginBottom: '8px'
                      }}>
                        <CheckCircle2 size={36} />
                      </div>
                      <div>
                        <h3 style={{ margin: '0 0 6px', fontSize: '20px', fontWeight: 600 }}>Job Setup Complete!</h3>
                        <p style={{ margin: '0 0 16px', fontSize: '14px', color: 'var(--text-secondary)', maxWidth: '420px', lineHeight: 1.5 }}>
                          Job Description weights and screening criteria are successfully saved. Now, evaluate applicant resumes to start compiling scores.
                        </p>
                      </div>

                      {/* Dropzone or button to run evaluation */}
                      <input 
                        type="file" 
                        ref={resumeInputRef} 
                        style={{ display: 'none' }} 
                        accept=".pdf,.docx" 
                        onChange={(e) => {
                          if (e.target.files && e.target.files[0]) {
                            setResumeFile(e.target.files[0]);
                            setEvaluationWizardStep(0);
                            setApiError(null);
                            setIsUploadOpen(true);
                          }
                        }}
                      />
                      <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                        <button 
                          type="button" 
                          className="btn-primary"
                          style={{ padding: '12px 24px', fontSize: '14px', fontWeight: 600 }}
                          onClick={() => resumeInputRef.current?.click()}
                        >
                          <Upload size={16} />
                          Upload Applicant Resume
                        </button>
                        <button 
                          type="button" 
                          className="btn-secondary"
                          style={{ padding: '12px 18px', fontSize: '14px' }}
                          onClick={() => {
                            setEditingSkills(selectedJob.skills || []);
                            setEditingGradYears(selectedJob.required_graduation_years?.join(", ") || "");
                            setEditingMinGpa(selectedJob.minimum_gpa !== undefined && selectedJob.minimum_gpa !== null ? String(selectedJob.minimum_gpa) : "");
                            setEditingOtherCriteria(selectedJob.other_eligibility_criteria || "");
                            setIsInlineSetupSaved(false);
                          }}
                        >
                          Configure Weights
                        </button>
                      </div>
                    </div>
                  ) : (
                    /* Active Folder Evaluations view */
                    <>
                      {/* KPIs Grid */}
                      <section className="stats-grid">
                        <div className="kpi-card">
                          <span className="kpi-title">Total Evaluated</span>
                          <div className="kpi-value-row">
                            <span className="kpi-value">{totalProcessed}</span>
                            <span className="kpi-trend success">Candidates</span>
                          </div>
                          <div className="progress-container">
                            <div className="progress-fill" style={{ width: "100%" }} />
                          </div>
                        </div>

                        <div className="kpi-card">
                          <span className="kpi-title">Shortlisted / Selected</span>
                          <div className="kpi-value-row">
                            <span className="kpi-value">{shortlistedOrSelectedCount}</span>
                            <span className="kpi-trend success">
                              {totalProcessed > 0 ? Math.round((shortlistedOrSelectedCount / totalProcessed) * 100) : 0}% Positive
                            </span>
                          </div>
                          <div className="progress-container">
                            <div 
                              className="progress-fill" 
                              style={{ width: `${totalProcessed > 0 ? (shortlistedOrSelectedCount / totalProcessed) * 100 : 0}%`, backgroundColor: "var(--color-success)" }} 
                            />
                          </div>
                        </div>

                        <div className="kpi-card">
                          <span className="kpi-title">Average Alignment Score</span>
                          <div className="kpi-value-row">
                            <span className="kpi-value">{avgMatchScore}%</span>
                            <span className="kpi-trend success">Weighted</span>
                          </div>
                          <div className="progress-container">
                            <div 
                              className="progress-fill" 
                              style={{ width: `${avgMatchScore}%` }} 
                            />
                          </div>
                        </div>
                      </section>

                      {/* Filtering & Table Layout */}
                      <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                        <div style={{ position: 'relative', flex: 1 }}>
                          <Search size={16} style={{ position: 'absolute', left: '14px', top: '12px', color: 'var(--text-muted)' }} />
                          <input 
                            type="text" 
                            placeholder="Search folder candidates by name, skills or GitHub..." 
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            style={{
                              width: '100%',
                              padding: '10px 16px 10px 42px',
                              backgroundColor: 'var(--bg-card)',
                              border: '1px solid var(--border-color)',
                              borderRadius: '10px',
                              color: 'var(--text-primary)',
                              fontSize: '14px',
                              outline: 'none',
                            }}
                          />
                        </div>
                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                          <button 
                            type="button"
                            className={`btn-secondary ${filterDecision === "all" ? "active" : ""}`}
                            style={{ padding: '8px 14px', height: '40px', backgroundColor: filterDecision === "all" ? "var(--bg-card-hover)" : "transparent" }}
                            onClick={() => setFilterDecision("all")}
                          >
                            All
                          </button>
                          <button 
                            type="button"
                            className={`btn-secondary ${filterDecision === "inprogress" ? "active" : ""}`}
                            style={{ padding: '8px 14px', height: '40px', borderColor: 'rgba(245, 158, 11, 0.2)', color: filterDecision === "inprogress" ? "#D97706" : "var(--text-primary)", backgroundColor: filterDecision === "inprogress" ? "rgba(245, 158, 11, 0.06)" : "transparent" }}
                            onClick={() => setFilterDecision("inprogress")}
                          >
                            In Progress
                          </button>
                          <button 
                            type="button"
                            className={`btn-secondary ${filterDecision === "shortlisted" ? "active" : ""}`}
                            style={{ padding: '8px 14px', height: '40px', borderColor: 'rgba(99, 102, 241, 0.2)', color: filterDecision === "shortlisted" ? "#4F46E5" : "var(--text-primary)", backgroundColor: filterDecision === "shortlisted" ? "rgba(99, 102, 241, 0.06)" : "transparent" }}
                            onClick={() => setFilterDecision("shortlisted")}
                          >
                            Shortlisted
                          </button>
                          <button 
                            type="button"
                            className={`btn-secondary ${filterDecision === "selected" ? "active" : ""}`}
                            style={{ padding: '8px 14px', height: '40px', borderColor: 'var(--color-success-border)', color: filterDecision === "selected" ? "var(--color-success)" : "var(--text-primary)", backgroundColor: filterDecision === "selected" ? "var(--color-success-bg)" : "transparent" }}
                            onClick={() => setFilterDecision("selected")}
                          >
                            Selected
                          </button>
                          <button 
                            type="button"
                            className={`btn-secondary ${filterDecision === "rejected" ? "active" : ""}`}
                            style={{ padding: '8px 14px', height: '40px', borderColor: 'var(--color-error-border)', color: filterDecision === "rejected" ? "var(--color-error)" : "var(--text-primary)", backgroundColor: filterDecision === "rejected" ? "var(--color-error-bg)" : "transparent" }}
                            onClick={() => setFilterDecision("rejected")}
                          >
                            Rejected
                          </button>
                        </div>
                      </div>

                      <div className="dashboard-content-split">
                        {/* Table Panel */}
                        <section className="table-section">
                          <div className="table-container">
                            <table className="candidate-table">
                              <thead>
                                <tr>
                                  <th>Candidate</th>
                                  <th>ATS Score</th>
                                  <th>JD Score</th>
                                  <th>Weighted Final</th>
                                  <th>Status</th>
                                  <th>View PDF</th>
                                </tr>
                              </thead>
                              <tbody>
                                {filteredCandidates.length > 0 ? (
                                  filteredCandidates.map((candidate) => (
                                    <tr 
                                      key={candidate.id}
                                      className={selectedCandidateId === candidate.id ? "selected" : ""}
                                      onClick={() => setSelectedCandidateId(candidate.id)}
                                    >
                                      <td>
                                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                                          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{candidate.name}</span>
                                          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>@{candidate.github_username} | {candidate.email}</span>
                                        </div>
                                      </td>
                                      <td>
                                        <div className="tooltip-wrapper">
                                          <span style={{ fontWeight: 500 }}>{candidate.score}</span>
                                          <span className="tooltip-text">
                                            {candidate.ats_reasoning_summary || "No reasoning summary available."}
                                          </span>
                                        </div>
                                        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>/100</span>
                                      </td>
                                      <td>
                                        <div className="tooltip-wrapper">
                                          <span style={{ fontWeight: 500 }}>{candidate.jd_score}</span>
                                          <span className="tooltip-text">
                                            {candidate.jd_reasoning_summary || "No reasoning summary available."}
                                          </span>
                                        </div>
                                        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>/100</span>
                                      </td>
                                      <td>
                                        <span style={{ fontWeight: 700, color: 'var(--color-accent)' }}>{Math.ceil(candidate.final_weighted_score)}%</span>
                                      </td>
                                      <td onClick={(e) => e.stopPropagation()}>
                                        {candidate.final_decision === "shortlisted" ? (
                                          <select
                                            value={candidate.final_decision}
                                            onChange={async (e) => {
                                              const newStatus = e.target.value;
                                              if (newStatus !== "selected" && newStatus !== "shortlisted") return;
                                              try {
                                                await axios.patch(`http://127.0.0.1:8000/api/candidates/${candidate.id}`, {
                                                  final_decision: newStatus
                                                });
                                                setCandidates(prev => prev.map(c => {
                                                  if (c.id === candidate.id) {
                                                    return { ...c, final_decision: newStatus };
                                                  }
                                                  return c;
                                                }));
                                              } catch (err) {
                                                console.error("Failed to update candidate status:", err);
                                              }
                                            }}
                                            style={{
                                              padding: '4px 10px',
                                              borderRadius: '20px',
                                              fontSize: '12px',
                                              fontWeight: 600,
                                              textTransform: 'none',
                                              border: '1px solid rgba(99, 102, 241, 0.18)',
                                              outline: 'none',
                                              cursor: 'pointer',
                                              backgroundColor: 'rgba(99, 102, 241, 0.08)',
                                              color: '#4F46E5',
                                            }}
                                          >
                                            <option value="shortlisted" style={{ color: '#4F46E5', backgroundColor: '#FFFFFF' }}>Shortlisted</option>
                                            <option value="selected" style={{ color: 'var(--color-success)', backgroundColor: '#FFFFFF' }}>Selected</option>
                                          </select>
                                        ) : (
                                          <span className={`badge-status ${candidate.final_decision}`}>
                                            {candidate.final_decision === "inprogress" ? (
                                              <>
                                                <Loader2 size={12} className="spinner-icon" style={{ animation: 'spinSlow 2s linear infinite' }} />
                                                In Progress
                                              </>
                                            ) : candidate.final_decision === "selected" ? (
                                              <>
                                                <CheckCircle2 size={12} />
                                                Selected
                                              </>
                                            ) : (
                                              <>
                                                <XCircle size={12} />
                                                Rejected
                                              </>
                                            )}
                                          </span>
                                        )}
                                      </td>
                                      <td onClick={(e) => e.stopPropagation()}>
                                        {(candidate.resume_filename || candidate.resume_gcs_uri) ? (
                                          <a
                                            href={`http://127.0.0.1:8000/api/candidates/${candidate.id}/resume`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            title="View PDF Resume"
                                            style={{
                                              display: 'inline-flex',
                                              alignItems: 'center',
                                              gap: '6px',
                                              fontSize: '12px',
                                              fontWeight: 600,
                                              textDecoration: 'none',
                                              padding: '6px 12px',
                                              borderRadius: '8px',
                                              backgroundColor: 'rgba(239, 68, 68, 0.08)',
                                              color: '#EF4444',
                                              border: '1px solid rgba(239, 68, 68, 0.2)',
                                              cursor: 'pointer',
                                              transition: 'all 0.2s',
                                            }}
                                            onMouseEnter={(e) => {
                                              e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.15)';
                                              e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.3)';
                                              e.currentTarget.style.transform = 'translateY(-1px)';
                                            }}
                                            onMouseLeave={(e) => {
                                              e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.08)';
                                              e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.2)';
                                              e.currentTarget.style.transform = 'none';
                                            }}
                                          >
                                            <FileText size={13} />
                                            <span>PDF</span>
                                          </a>
                                        ) : (
                                          <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>N/A</span>
                                        )}
                                      </td>
                                    </tr>
                                  ))
                                ) : (
                                  <tr>
                                    <td colSpan={6} style={{ textAlign: 'center', padding: '32px', color: 'var(--text-secondary)' }}>
                                      No candidate evaluations listed under this job role folder.
                                    </td>
                                  </tr>
                                )}
                              </tbody>
                            </table>
                          </div>
                        </section>

                        {/* Drill Down Detail Drawer */}
                        {selectedCandidate && (
                          <section className="detail-drawer">
                            <div className="drawer-header">
                              <div>
                                <h3>Candidate Evaluation</h3>
                                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Selected: {selectedCandidate.name}</span>
                              </div>
                              <div className="drawer-close" onClick={() => setSelectedCandidateId("")}>
                                <ChevronRight size={20} />
                              </div>
                            </div>

                            {/* Sub tabs inside drawer */}
                            <div style={{ 
                              display: 'flex', 
                              borderBottom: '1px solid var(--border-color)', 
                              backgroundColor: 'var(--bg-card-hover)',
                              padding: '0 8px'
                            }}>
                              <button 
                                type="button"
                                style={{
                                  flex: 1,
                                  padding: '12px 6px',
                                  backgroundColor: 'transparent',
                                  border: 'none',
                                  color: activeDrawerTab === 'brief' ? 'var(--color-accent)' : 'var(--text-secondary)',
                                  fontSize: '12px',
                                  fontWeight: 600,
                                  cursor: 'pointer',
                                  borderBottom: activeDrawerTab === 'brief' ? '2px solid var(--color-accent)' : '2px solid transparent',
                                  transition: 'all 0.2s',
                                }}
                                onClick={() => setActiveDrawerTab('brief')}
                              >
                                Brief & Score
                              </button>
                              <button 
                                type="button"
                                style={{
                                  flex: 1,
                                  padding: '12px 6px',
                                  backgroundColor: 'transparent',
                                  border: 'none',
                                  color: activeDrawerTab === 'profile' ? 'var(--color-accent)' : 'var(--text-secondary)',
                                  fontSize: '12px',
                                  fontWeight: 600,
                                  cursor: 'pointer',
                                  borderBottom: activeDrawerTab === 'profile' ? '2px solid var(--color-accent)' : '2px solid transparent',
                                  transition: 'all 0.2s',
                                }}
                                onClick={() => setActiveDrawerTab('profile')}
                              >
                                CV Profile
                              </button>
                              <button 
                                type="button"
                                style={{
                                  flex: 1,
                                  padding: '12px 6px',
                                  backgroundColor: 'transparent',
                                  border: 'none',
                                  color: activeDrawerTab === 'github' ? 'var(--color-accent)' : 'var(--text-secondary)',
                                  fontSize: '12px',
                                  fontWeight: 600,
                                  cursor: 'pointer',
                                  borderBottom: activeDrawerTab === 'github' ? '2px solid var(--color-accent)' : '2px solid transparent',
                                  transition: 'all 0.2s',
                                }}
                                onClick={() => setActiveDrawerTab('github')}
                              >
                                GitHub Audit
                              </button>
                              <button 
                                type="button"
                                style={{
                                  flex: 1,
                                  padding: '12px 6px',
                                  backgroundColor: 'transparent',
                                  border: 'none',
                                  color: activeDrawerTab === 'questions' ? 'var(--color-accent)' : 'var(--text-secondary)',
                                  fontSize: '12px',
                                  fontWeight: 600,
                                  cursor: 'pointer',
                                  borderBottom: activeDrawerTab === 'questions' ? '2px solid var(--color-accent)' : '2px solid transparent',
                                  transition: 'all 0.2s',
                                }}
                                onClick={() => setActiveDrawerTab('questions')}
                              >
                                Questions
                              </button>
                            </div>

                            <div className="drawer-body">
                              {activeDrawerTab === 'brief' && (
                                <>
                                  <div className="detail-card">
                                    <div className="detail-card-title">
                                      <Sparkles size={14} />
                                      <span>Hiring Manager Brief</span>
                                    </div>
                                    <div className="brief-content" style={{ fontSize: '13px', lineHeight: 1.5 }}>
                                      {renderMarkdown(selectedCandidate.hiring_manager_brief)}
                                    </div>
                                  </div>



                                  <div className="detail-card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
                                    <div style={{ display: 'flex', gap: '16px', width: '100%', justifyContent: 'space-around', alignItems: 'center' }}>
                                      {/* Main Combined Score */}
                                      <CircularProgress 
                                        score={Math.ceil(selectedCandidate.final_weighted_score)} 
                                        size={110} 
                                        strokeWidth={9} 
                                        color="var(--color-accent)" 
                                        label="OVERALL" 
                                      />
                                      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                          <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--color-accent)' }} />
                                          <span style={{ fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)' }}>
                                            JD Alignment: <strong>{selectedCandidate.jd_score}%</strong>
                                          </span>
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                          <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--color-success)' }} />
                                          <span style={{ fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)' }}>
                                            ATS Matrix: <strong>{selectedCandidate.score}%</strong>
                                          </span>
                                        </div>
                                        {selectedCandidate.final_decision === "shortlisted" ? (
                                          <select
                                            value={selectedCandidate.final_decision}
                                            onChange={async (e) => {
                                              const newStatus = e.target.value;
                                              if (newStatus !== "selected" && newStatus !== "shortlisted") return;
                                              try {
                                                await axios.patch(`http://127.0.0.1:8000/api/candidates/${selectedCandidate.id}`, {
                                                  final_decision: newStatus
                                                });
                                                setCandidates(prev => prev.map(c => {
                                                  if (c.id === selectedCandidate.id) {
                                                    return { ...c, final_decision: newStatus };
                                                  }
                                                  return c;
                                                }));
                                              } catch (err) {
                                                console.error("Failed to update candidate status:", err);
                                              }
                                            }}
                                            style={{
                                              padding: '6px 12px',
                                              borderRadius: '20px',
                                              fontSize: '11px',
                                              fontWeight: 700,
                                              textTransform: 'uppercase',
                                              alignSelf: 'flex-start',
                                              border: '1px solid rgba(99, 102, 241, 0.18)',
                                              outline: 'none',
                                              cursor: 'pointer',
                                              backgroundColor: 'rgba(99, 102, 241, 0.08)',
                                              color: '#4F46E5',
                                            }}
                                          >
                                            <option value="shortlisted" style={{ color: '#4F46E5', backgroundColor: '#FFFFFF' }}>Shortlisted</option>
                                            <option value="selected" style={{ color: 'var(--color-success)', backgroundColor: '#FFFFFF' }}>Selected</option>
                                          </select>
                                        ) : (
                                          <span className={`badge-status ${selectedCandidate.final_decision}`}>
                                            {selectedCandidate.final_decision === "inprogress" ? (
                                              <>
                                                <Loader2 size={12} className="spinner-icon" style={{ animation: 'spinSlow 2s linear infinite' }} />
                                                In Progress
                                              </>
                                            ) : selectedCandidate.final_decision === "selected" ? (
                                              <>
                                                <CheckCircle2 size={12} />
                                                Selected
                                              </>
                                            ) : (
                                              <>
                                                <XCircle size={12} />
                                                Rejected
                                              </>
                                            )}
                                          </span>
                                        )}
                                      </div>
                                    </div>

                                    {/* Mini scores row */}
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                      <div className="detail-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '14px', gap: '10px' }}>
                                        <CircularProgress 
                                          score={selectedCandidate.score} 
                                          size={75} 
                                          strokeWidth={6} 
                                          color="var(--color-success)" 
                                          label="ATS" 
                                        />
                                        <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>ATS Compliance</span>
                                      </div>
                                      <div className="detail-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '14px', gap: '10px' }}>
                                        <CircularProgress 
                                          score={selectedCandidate.jd_score} 
                                          size={75} 
                                          strokeWidth={6} 
                                          color="var(--color-accent)" 
                                          label="JD" 
                                        />
                                        <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>JD Alignment</span>
                                      </div>
                                    </div>
                                  </div>
                                </>
                              )}

                              {activeDrawerTab === 'profile' && (
                                <>
                                  <div className="detail-card">
                                    <div className="detail-card-title">
                                      <Users size={14} />
                                      <span>Contact Information</span>
                                    </div>
                                    <div className="meta-list">
                                      <div className="meta-item">
                                        <span className="meta-label">Email:</span>
                                        <span className="meta-value">{selectedCandidate.email}</span>
                                      </div>
                                      <div className="meta-item">
                                        <span className="meta-label">Phone:</span>
                                        <span className="meta-value">{selectedCandidate.phone}</span>
                                      </div>
                                      <div className="meta-item">
                                        <span className="meta-label">GitHub Username:</span>
                                        <span className="meta-value">@{selectedCandidate.github_username}</span>
                                      </div>
                                    </div>
                                  </div>

                                  <div className="detail-card">
                                    <div className="detail-card-title">
                                      <BookOpen size={14} />
                                      <span>Education History</span>
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                      {selectedCandidate.education.map((edu, idx) => (
                                        <div key={idx} style={{ borderBottom: idx < selectedCandidate.education.length - 1 ? '1px solid var(--border-color)' : 'none', paddingBottom: '8px' }}>
                                          <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>{edu.institution}</span>
                                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                                            <span>{edu.degree}</span>
                                            <span>GPA: {edu.gpa}</span>
                                          </div>
                                          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{edu.duration}</span>
                                        </div>
                                      ))}
                                    </div>
                                  </div>

                                  <div className="detail-card">
                                    <div className="detail-card-title">
                                      <Briefcase size={14} />
                                      <span>Work Experience</span>
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                      {selectedCandidate.experience.length > 0 ? (
                                        selectedCandidate.experience.map((exp, idx) => (
                                          <div key={idx} style={{ borderBottom: idx < selectedCandidate.experience.length - 1 ? '1px solid var(--border-color)' : 'none', paddingBottom: '8px' }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                              <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>{exp.company}</span>
                                              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{exp.duration}</span>
                                            </div>
                                            <span style={{ fontSize: '12px', color: 'var(--color-accent)', display: 'block', marginTop: '2px' }}>{exp.role}</span>
                                            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: '4px 0 0' }}>{exp.description}</p>
                                          </div>
                                        ))
                                      ) : (
                                        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>No formal work experience listed.</span>
                                      )}
                                    </div>
                                  </div>

                                  <div className="detail-card">
                                    <div className="detail-card-title">
                                      <Sparkles size={14} />
                                      <span>Key Projects</span>
                                    </div>
                                    <div className="project-list">
                                      {selectedCandidate.projects.map((proj, idx) => (
                                        <div key={idx} className="project-item">
                                          <span className="project-name">{proj.title}</span>
                                          <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: '4px 0 0' }}>{proj.description}</p>
                                          <div className="project-tech">
                                            {proj.technologies.map((t, tid) => (
                                              <span key={tid} className="tech-tag">{t}</span>
                                            ))}
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  </div>

                                  <div className="detail-card">
                                    <div className="detail-card-title">
                                      <Settings size={14} />
                                      <span>Core Tech Skills</span>
                                    </div>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                      {selectedCandidate.skills.map((skill, idx) => (
                                        <span key={idx} className="tech-tag">{skill}</span>
                                      ))}
                                    </div>
                                  </div>
                                </>
                              )}

                              {activeDrawerTab === 'github' && (
                                <>
                                  <div className="detail-card">
                                    <div className="detail-card-title">
                                      <GithubIcon size={14} />
                                      <span>GitHub Verified Stats</span>
                                    </div>
                                    {selectedCandidate.github_data ? (
                                      <div className="meta-list">
                                        <div className="meta-item">
                                          <span className="meta-label">Profile Account:</span>
                                          <span className="meta-value">@{selectedCandidate.github_data.name}</span>
                                        </div>
                                        <div className="meta-item">
                                          <span className="meta-label">Created:</span>
                                          <span className="meta-value">{new Date(selectedCandidate.github_data.account_created).toLocaleDateString()}</span>
                                        </div>
                                        <div className="meta-item">
                                          <span className="meta-label">Public Repos:</span>
                                          <span className="meta-value">{selectedCandidate.github_data.total_public_repositories} repositories</span>
                                        </div>
                                        <div className="meta-item">
                                          <span className="meta-label">Bio:</span>
                                          <span className="meta-value" style={{ fontStyle: 'italic' }}>{selectedCandidate.github_data.bio || "None"}</span>
                                        </div>
                                      </div>
                                    ) : (
                                      <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>No public GitHub profile found or username mismatch.</span>
                                    )}
                                  </div>

                                  <div className="detail-card">
                                    <div className="detail-card-title">
                                      <ShieldCheck size={14} />
                                      <span>Project Verification Log</span>
                                    </div>
                                    <div className="brief-content" style={{ fontSize: '12.5px', color: 'var(--text-secondary)' }}>
                                      {renderMarkdown(selectedCandidate.project_verification)}
                                    </div>
                                  </div>

                                  {selectedCandidate.github_data && selectedCandidate.github_data.recent_projects.length > 0 && (
                                    <div className="detail-card">
                                      <div className="detail-card-title">
                                        <FileSpreadsheet size={14} />
                                        <span>Recent GitHub Activities</span>
                                      </div>
                                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                        {selectedCandidate.github_data.recent_projects.map((repo, idx) => (
                                          <div key={idx} style={{ backgroundColor: 'var(--bg-card-hover)', padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                              <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>{repo.name}</span>
                                              <span style={{ fontSize: '11px', color: 'var(--color-accent)' }}>★ {repo.stars}</span>
                                            </div>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                              <span>{repo.languages.join(', ') || 'Documentation'}</span>
                                              <span>Active: {new Date(repo.last_active).toLocaleDateString()}</span>
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </>
                              )}

                              {activeDrawerTab === 'questions' && (
                                <>
                                  <div className="detail-card">
                                    <div className="detail-card-title">
                                      <Sparkles size={14} />
                                      <span>Interview Guide</span>
                                    </div>
                                    <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: 0 }}>
                                      These custom technical questions are dynamically synthesized by our LLM Agent based on verified GitHub code gaps and CV contradictions.
                                    </p>
                                  </div>

                                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                    {selectedCandidate.interview_questions.map((question, idx) => (
                                      <div key={idx} className="question-item" style={{ backgroundColor: 'var(--bg-card-hover)', padding: '16px', borderRadius: '12px', border: '1px solid var(--border-color)' }}>
                                        <span className="question-number">Question {idx + 1}</span>
                                        <p className="question-text" style={{ margin: '6px 0 0', fontWeight: 500 }}>{question}</p>
                                      </div>
                                    ))}
                                  </div>

                                  <div className="detail-card" style={{ marginTop: '8px' }}>
                                    <div className="detail-card-title">
                                      <Mail size={14} />
                                      <span>Generated Recruiter Email</span>
                                    </div>
                                    <div 
                                      style={{ 
                                        fontSize: '12.5px', 
                                        lineHeight: 1.4, 
                                        color: 'var(--text-primary)', 
                                        backgroundColor: 'var(--bg-card-hover)', 
                                        padding: '12px', 
                                        borderRadius: '8px', 
                                        border: '1px dashed var(--border-hover)',
                                        whiteSpace: 'pre-wrap'
                                      }}
                                    >
                                      {selectedCandidate.candidate_email}
                                    </div>
                                  </div>
                                </>
                              )}
                            </div>
                          </section>
                        )}
                      </div>
                    </>
                  )}
                </>
              ) : (
                /* Select Folder Empty State */
                <div 
                  style={{ 
                    flex: 1, 
                    display: 'flex', 
                    flexDirection: 'column', 
                    alignItems: 'center', 
                    justifyContent: 'center',
                    border: '1px solid var(--border-color)',
                    backgroundColor: 'var(--bg-card)',
                    borderRadius: '16px',
                    padding: '40px',
                    textAlign: 'center',
                    gap: '12px'
                  }}
                >
                  <FolderOpen size={48} style={{ color: 'var(--text-muted)' }} />
                  <div>
                    <h3 style={{ margin: '0 0 4px', fontSize: '18px' }}>Select or Create a Job Folder</h3>
                    <p style={{ margin: 0, fontSize: '14px', color: 'var(--text-secondary)' }}>
                      To evaluate applicants, choose an active folder on the left or create a new job role folder.
                    </p>
                  </div>
                  <button 
                    type="button" 
                    className="btn-primary" 
                    onClick={() => setIsCreateJobOpen(true)}
                  >
                    <Plus size={14} />
                    Create New Folder
                  </button>
                </div>
              )}
            </div>
          </div>
        </main>
      ) : (
        <main className="main-content">
          <header className="dashboard-header">
            <div className="header-title-section">
              <h1>Settings & Integrations</h1>
              <p>Configure LLM reasoning prompts, GitHub access keys, and API tokens.</p>
            </div>
            <button type="button" className="btn-secondary" onClick={() => setActiveSidebarTab("dashboard")}>
              Back to Candidates
            </button>
          </header>

          <section style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div className="detail-card" style={{ padding: '24px' }}>
              <h3 style={{ margin: '0 0 16px' }}>API Configurations</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>FastAPI Gateway URL</label>
                  <input type="text" value="http://127.0.0.1:8000" readOnly style={{ backgroundColor: 'var(--bg-main)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '10px', color: 'var(--text-primary)', fontSize: '13px' }} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>LLM Inference Engine</label>
                  <input type="text" value="gemini-3.1-flash-lite" readOnly style={{ backgroundColor: 'var(--bg-main)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '10px', color: 'var(--text-primary)', fontSize: '13px' }} />
                </div>
              </div>
            </div>

            <div className="detail-card" style={{ padding: '24px' }}>
              <h3 style={{ margin: '0 0 16px' }}>System Status</h3>
              <div className="meta-list">
                <div className="meta-item">
                  <span className="meta-label">FastAPI Status:</span>
                  <span className="meta-value" style={{ color: 'var(--color-success)' }}>● Operational</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">LLM Quota Availability:</span>
                  <span className="meta-value" style={{ color: 'var(--color-success)' }}>● Normal</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">GitHub Rate Limit Status:</span>
                  <span className="meta-value">4,996 / hour (Authenticated API)</span>
                </div>
              </div>
            </div>
          </section>
        </main>
      )}

      {/* Create Job Folder Modal Overlay */}
      {isCreateJobOpen && (
        <div className="modal-backdrop">
          <div className="upload-modal" style={{ width: '400px', padding: '24px' }}>
            <div className="modal-header">
              <h2>Create New Job Role</h2>
              <div className="modal-close" onClick={() => setIsCreateJobOpen(false)}>
                <X size={18} />
              </div>
            </div>
            
            <div className="form-group" style={{ marginTop: '12px' }}>
              <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>Job Title / Role Name</label>
              <input 
                type="text" 
                className="form-input" 
                placeholder="e.g. AI Engineer Intern"
                value={newJobName}
                onChange={(e) => setNewJobName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateJobFolder()}
              />
            </div>

            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '20px' }}>
              <button 
                type="button" 
                className="btn-secondary" 
                onClick={() => setIsCreateJobOpen(false)}
              >
                Cancel
              </button>
              <button 
                type="button" 
                className="btn-primary" 
                disabled={!newJobName.trim()}
                onClick={handleCreateJobFolder}
              >
                Create Folder
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Job Confirmation Modal Overlay */}
      {jobToDeleteId && (
        <div className="modal-backdrop">
          <div className="upload-modal" style={{ width: '400px', padding: '24px' }}>
            <div className="modal-header">
              <h2 style={{ color: 'var(--color-error)' }}>Delete Job Role</h2>
              <div className="modal-close" onClick={() => setJobToDeleteId(null)}>
                <X size={18} />
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '8px' }}>
              <p style={{ margin: 0, fontSize: '14px', lineHeight: 1.5, color: 'var(--text-secondary)' }}>
                Are you sure you want to delete the job role <strong>"{jobs.find(j => j._id === jobToDeleteId)?.name}"</strong>?
              </p>
              <div style={{ padding: '12px', borderRadius: '8px', backgroundColor: 'var(--color-error-bg)', border: '1px dashed var(--color-error-border)' }}>
                <p style={{ margin: 0, fontSize: '12px', lineHeight: 1.4, color: 'var(--color-error)', fontWeight: 500 }}>
                  ⚠️ Warning: This will permanently delete the job description and all associated candidate evaluations. This action cannot be undone.
                </p>
              </div>
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '12px' }}>
                <button 
                  type="button" 
                  className="btn-secondary" 
                  onClick={() => setJobToDeleteId(null)}
                >
                  Cancel
                </button>
                <button 
                  type="button" 
                  className="btn-danger-solid"
                  onClick={async () => {
                    const id = jobToDeleteId;
                    setJobToDeleteId(null);
                    await handleDeleteJob(id);
                  }}
                >
                  Delete Permanently
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Evaluate Candidate Resume Modal Overlay */}
      {isUploadOpen && selectedJob && (
        <div className="modal-backdrop">
          <div className="upload-modal" style={{ width: evaluationWizardStep === 1 && !isUploading ? '560px' : '520px', transition: 'width 0.3s ease-in-out' }}>
            <div className="modal-header">
              <div>
                <h2>{evaluationWizardStep === 0 ? "Evaluate Applicant Resume" : "Configure Screening Criteria"}</h2>
                <p>
                  {evaluationWizardStep === 0 
                    ? "Upload candidate resume to run evaluation in folder: " 
                    : "Customize skills evaluation and eligibility criteria for: "}
                  <strong>{selectedJob.name}</strong>
                </p>
              </div>
              <div className="modal-close" onClick={() => !isUploading && setIsUploadOpen(false)}>
                <X size={20} />
              </div>
            </div>

            {isUploading ? (
              <div className="loader-stepper">
                <div className="loading-spinner-row">
                  <Loader2 className="spinner-icon" size={24} />
                  <span className="loader-status">Running LangGraph Multi-Agent Pipeline...</span>
                </div>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '0 0 8px' }}>
                  Evaluating resume against stored JD ({selectedJob.jd_filename}). Takes about 10-15 seconds.
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '12px' }}>
                  {PIPELINE_STEPS.map((stepMsg, idx) => {
                    let stepClass = "step-item";
                    if (idx < uploadStep) stepClass += " completed";
                    else if (idx === uploadStep) stepClass += " active";
                    
                    return (
                      <div key={idx} className={stepClass}>
                        <div className="step-dot" />
                        <span>{stepMsg}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : evaluationWizardStep === 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {apiError && (
                  <div style={{ backgroundColor: 'var(--color-error-bg)', border: '1px solid var(--color-error-border)', color: 'var(--color-error)', padding: '12px 16px', borderRadius: '10px', fontSize: '13px' }}>
                    {apiError}
                  </div>
                )}

                {/* Resume Upload Dropzone */}
                <div className="upload-group">
                  <label className="upload-label">Candidate Resume (PDF/DOCX)</label>
                  <input 
                    type="file" 
                    ref={resumeInputRef} 
                    style={{ display: 'none' }} 
                    accept=".pdf,.docx" 
                    onChange={(e) => e.target.files && setResumeFile(e.target.files[0])}
                  />
                  <div 
                    className="file-dropzone" 
                    onDragOver={handleDragOver}
                    onDrop={handleDropResume}
                    onClick={() => resumeInputRef.current?.click()}
                  >
                    <Upload className="file-dropzone-icon" size={24} />
                    {resumeFile ? (
                      <div className="file-selected-info">
                        <Check size={16} />
                        <span>Selected: {resumeFile.name}</span>
                      </div>
                    ) : (
                      <span>Drag & drop candidate CV or <span className="highlight">browse</span></span>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '12px' }}>
                  <button 
                    type="button" 
                    className="btn-secondary" 
                    onClick={() => setIsUploadOpen(false)}
                  >
                    Cancel
                  </button>
                  <button 
                    type="button" 
                    className="btn-secondary" 
                    disabled={!resumeFile}
                    onClick={() => {
                      setEditingSkills(selectedJob.skills || []);
                      setEditingGradYears(selectedJob.required_graduation_years?.join(", ") || "");
                      setEditingMinGpa(selectedJob.minimum_gpa !== undefined && selectedJob.minimum_gpa !== null ? String(selectedJob.minimum_gpa) : "");
                      setEditingOtherCriteria(selectedJob.other_eligibility_criteria || "");
                      setEvaluationWizardStep(1);
                    }}
                  >
                    Configure weights
                  </button>
                  <button 
                    type="button" 
                    className="btn-primary" 
                    disabled={!resumeFile}
                    onClick={triggerEvaluation}
                  >
                    Run Evaluation
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {apiError && (
                  <div style={{ backgroundColor: 'var(--color-error-bg)', border: '1px solid var(--color-error-border)', color: 'var(--color-error)', padding: '12px 16px', borderRadius: '10px', fontSize: '13px' }}>
                    {apiError}
                  </div>
                )}

                <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)' }}>
                  Review and customize the skills evaluation weights and eligibility criteria extracted from the Job Description before running candidate screening.
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxHeight: '320px', overflowY: 'auto', paddingRight: '4px' }}>
                  {/* Skills Section */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', margin: '0' }}>Skill Weights</h3>
                    {editingSkills.length === 0 ? (
                      <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)', fontSize: '13px', border: '1px dashed var(--border-color)', borderRadius: '8px' }}>
                        No skills configured. Click "Add Custom Skill" below to define skills.
                      </div>
                    ) : (
                      editingSkills.map((skill, index) => (
                        <div key={index} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 14px', backgroundColor: 'var(--bg-card-hover)', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                          <input 
                            type="text" 
                            style={{
                              flex: '1.2',
                              padding: '6px 10px',
                              border: '1px solid var(--border-color)',
                              borderRadius: '6px',
                              fontSize: '13px',
                              color: 'var(--text-primary)',
                              backgroundColor: '#FFFFFF',
                              minWidth: '100px'
                            }}
                            value={skill.name}
                            onChange={(e) => updateSkillName(index, e.target.value)}
                            placeholder="Skill Name"
                          />
                          
                          <div style={{ flex: '2', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <input 
                              type="range" 
                              min="0" 
                              max="100" 
                              style={{
                                flex: 1,
                                cursor: 'pointer',
                                accentColor: 'var(--color-accent)'
                              }}
                              value={skill.weight}
                              onChange={(e) => updateSkillWeight(index, parseInt(e.target.value))}
                            />
                            <span style={{ fontSize: '13px', fontWeight: 600, minWidth: '40px', textAlign: 'right', color: 'var(--text-primary)' }}>
                              {skill.weight}%
                            </span>
                          </div>

                          <button 
                            type="button"
                            style={{
                              padding: '6px',
                              borderRadius: '6px',
                              border: 'none',
                              backgroundColor: 'transparent',
                              color: 'var(--text-muted)',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center'
                            }}
                            onClick={() => deleteSkill(index)}
                            title="Delete Skill"
                          >
                            <X size={16} />
                          </button>
                        </div>
                      ))
                    )}
                  </div>

                  {/* Pre-Screening Section */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
                    <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', margin: '0' }}>Pre-Screening Eligibility Criteria</h3>
                    
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>Graduation Years (comma separated)</label>
                        <input 
                          type="text" 
                          placeholder="e.g. 2025, 2026"
                          style={{
                            padding: '8px 12px',
                            border: '1px solid var(--border-color)',
                            borderRadius: '6px',
                            fontSize: '13px',
                            color: 'var(--text-primary)',
                            backgroundColor: '#FFFFFF',
                          }}
                          value={editingGradYears}
                          onChange={(e) => setEditingGradYears(e.target.value)}
                        />
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>Minimum GPA</label>
                        <input 
                          type="text" 
                          placeholder="e.g. 3.0"
                          style={{
                            padding: '8px 12px',
                            border: '1px solid var(--border-color)',
                            borderRadius: '6px',
                            fontSize: '13px',
                            color: 'var(--text-primary)',
                            backgroundColor: '#FFFFFF',
                          }}
                          value={editingMinGpa}
                          onChange={(e) => setEditingMinGpa(e.target.value)}
                        />
                      </div>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>Other Eligibility requirements (work authorization, etc.)</label>
                      <textarea 
                        placeholder="e.g. Must be currently authorized to work in the US without visa sponsorship."
                        style={{
                          padding: '8px 12px',
                          border: '1px solid var(--border-color)',
                          borderRadius: '6px',
                          fontSize: '13px',
                          color: 'var(--text-primary)',
                          backgroundColor: '#FFFFFF',
                          resize: 'vertical',
                          height: '60px',
                          fontFamily: 'inherit'
                        }}
                        value={editingOtherCriteria}
                        onChange={(e) => setEditingOtherCriteria(e.target.value)}
                      />
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
                  <button 
                    type="button"
                    className="btn-secondary"
                    style={{ padding: '8px 12px', fontSize: '13px' }}
                    onClick={addSkill}
                  >
                    <Plus size={14} />
                    Add Custom Skill
                  </button>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                      Total Weight:
                    </span>
                    <span 
                      style={{ 
                        fontSize: '15px', 
                        fontWeight: 700, 
                        color: editingSkills.reduce((sum, s) => sum + s.weight, 0) === 100 ? 'var(--color-success)' : 'var(--color-error)' 
                      }}
                    >
                      {editingSkills.reduce((sum, s) => sum + s.weight, 0)}%
                    </span>
                  </div>
                </div>

                {editingSkills.reduce((sum, s) => sum + s.weight, 0) !== 100 && (
                  <span style={{ fontSize: '12px', color: 'var(--color-error)', alignSelf: 'flex-end', marginTop: '-12px' }}>
                    * Weights must sum to exactly 100% to save.
                  </span>
                )}

                <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '12px' }}>
                  <button 
                    type="button" 
                    className="btn-secondary" 
                    onClick={() => setEvaluationWizardStep(0)}
                  >
                    Back
                  </button>
                  <button 
                    type="button" 
                    className="btn-primary" 
                    disabled={editingSkills.reduce((sum, s) => sum + s.weight, 0) !== 100}
                    onClick={saveCriteriaAndTriggerEvaluation}
                  >
                    <Sparkles size={14} />
                    Run Agent Pipeline
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      {isSkillsModalOpen && selectedJob && (
        <div className="modal-backdrop">
          <div className="upload-modal" style={{ width: '560px', padding: '28px' }}>
            <div className="modal-header">
              <div>
                <h2>Configure Job Criteria</h2>
                <p>Customize skills evaluation and eligibility criteria for: <strong>{selectedJob.name}</strong></p>
              </div>
              <div className="modal-close" onClick={() => !isSavingSkills && setIsSkillsModalOpen(false)}>
                <X size={20} />
              </div>
            </div>

            {skillsSaveError && (
              <div style={{ backgroundColor: 'var(--color-error-bg)', border: '1px solid var(--color-error-border)', color: 'var(--color-error)', padding: '10px 14px', borderRadius: '8px', fontSize: '13px' }}>
                {skillsSaveError}
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxHeight: '420px', overflowY: 'auto', paddingRight: '4px' }}>
              {/* Skills section */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', margin: '0' }}>Skill Weights</h3>
                {editingSkills.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)', fontSize: '13px', border: '1px dashed var(--border-color)', borderRadius: '8px' }}>
                    No skills configured for this job role. Click "Add Custom Skill" below to define skills.
                  </div>
                ) : (
                  editingSkills.map((skill, index) => (
                    <div key={index} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 14px', backgroundColor: 'var(--bg-card-hover)', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                      <input 
                        type="text" 
                        style={{
                          flex: '1.2',
                          padding: '6px 10px',
                          border: '1px solid var(--border-color)',
                          borderRadius: '6px',
                          fontSize: '13px',
                          color: 'var(--text-primary)',
                          backgroundColor: '#FFFFFF',
                          minWidth: '100px'
                        }}
                        value={skill.name}
                        onChange={(e) => updateSkillName(index, e.target.value)}
                        placeholder="Skill Name"
                      />
                      
                      <div style={{ flex: '2', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <input 
                          type="range" 
                          min="0" 
                          max="100" 
                          style={{
                            flex: 1,
                            cursor: 'pointer',
                            accentColor: 'var(--color-accent)'
                          }}
                          value={skill.weight}
                          onChange={(e) => updateSkillWeight(index, parseInt(e.target.value))}
                        />
                        <span style={{ fontSize: '13px', fontWeight: 600, minWidth: '40px', textAlign: 'right', color: 'var(--text-primary)' }}>
                          {skill.weight}%
                        </span>
                      </div>

                      <button 
                        type="button"
                        style={{
                          padding: '6px',
                          borderRadius: '6px',
                          border: 'none',
                          backgroundColor: 'transparent',
                          color: 'var(--text-muted)',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center'
                        }}
                        onClick={() => deleteSkill(index)}
                        title="Delete Skill"
                      >
                        <X size={16} />
                      </button>
                    </div>
                  ))
                )}
              </div>

              {/* Pre-Screening Section */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
                <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', margin: '0' }}>Pre-Screening Eligibility Criteria</h3>
                
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>Graduation Years (comma separated)</label>
                    <input 
                      type="text" 
                      placeholder="e.g. 2025, 2026"
                      style={{
                        padding: '8px 12px',
                        border: '1px solid var(--border-color)',
                        borderRadius: '6px',
                        fontSize: '13px',
                        color: 'var(--text-primary)',
                        backgroundColor: '#FFFFFF',
                      }}
                      value={editingGradYears}
                      onChange={(e) => setEditingGradYears(e.target.value)}
                    />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>Minimum GPA</label>
                    <input 
                      type="text" 
                      placeholder="e.g. 3.0"
                      style={{
                        padding: '8px 12px',
                        border: '1px solid var(--border-color)',
                        borderRadius: '6px',
                        fontSize: '13px',
                        color: 'var(--text-primary)',
                        backgroundColor: '#FFFFFF',
                      }}
                      value={editingMinGpa}
                      onChange={(e) => setEditingMinGpa(e.target.value)}
                    />
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>Other Eligibility requirements (work authorization, etc.)</label>
                  <textarea 
                    placeholder="e.g. Must be currently authorized to work in the US without visa sponsorship."
                    style={{
                      padding: '8px 12px',
                      border: '1px solid var(--border-color)',
                      borderRadius: '6px',
                      fontSize: '13px',
                      color: 'var(--text-primary)',
                      backgroundColor: '#FFFFFF',
                      resize: 'vertical',
                      height: '60px',
                      fontFamily: 'inherit'
                    }}
                    value={editingOtherCriteria}
                    onChange={(e) => setEditingOtherCriteria(e.target.value)}
                  />
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
              <button 
                type="button"
                className="btn-secondary"
                style={{ padding: '8px 12px', fontSize: '13px' }}
                onClick={addSkill}
              >
                <Plus size={14} />
                Add Custom Skill
              </button>

              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                  Total Weight:
                </span>
                <span 
                  style={{ 
                    fontSize: '15px', 
                    fontWeight: 700, 
                    color: editingSkills.reduce((sum, s) => sum + s.weight, 0) === 100 ? 'var(--color-success)' : 'var(--color-error)' 
                  }}
                >
                  {editingSkills.reduce((sum, s) => sum + s.weight, 0)}%
                </span>
              </div>
            </div>

            {editingSkills.reduce((sum, s) => sum + s.weight, 0) !== 100 && (
              <span style={{ fontSize: '12px', color: 'var(--color-error)', alignSelf: 'flex-end', marginTop: '-12px' }}>
                * Weights must sum to exactly 100% to save.
              </span>
            )}

            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '12px' }}>
              <button 
                type="button" 
                className="btn-secondary" 
                disabled={isSavingSkills}
                onClick={() => setIsSkillsModalOpen(false)}
              >
                Cancel
              </button>
              <button 
                type="button" 
                className="btn-primary" 
                disabled={editingSkills.reduce((sum, s) => sum + s.weight, 0) !== 100 || isSavingSkills}
                onClick={saveSkills}
              >
                {isSavingSkills ? (
                  <>
                    <Loader2 className="spinner-icon" size={14} />
                    Saving Weights...
                  </>
                ) : (
                  <>
                    <Check size={14} />
                    {candidates.filter(c => c.job_id === selectedJobId).length === 0 ? "Save Weights" : "Re-Evaluate"}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
