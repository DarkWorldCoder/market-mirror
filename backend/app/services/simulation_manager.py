"""
OASIS simulation manager
Manages parallel Twitter and Reddit simulations
Uses preset scripts plus LLM-generated configuration parameters
"""

import os
import json
import shutil
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import ZepEntityReader, FilteredEntities, EntityNode
from .oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile
from .simulation_config_generator import SimulationConfigGenerator, SimulationParameters
from . import persona_planner
from ..utils.locale import t

logger = get_logger('mirofish.simulation')


class SimulationStatus(str, Enum):
    """Simulation status"""
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    PAUSED = "paused"
    STOPPED = "stopped"      # the simulation was stopped by hand
    COMPLETED = "completed"  # the simulation finished on its own
    FAILED = "failed"


class PlatformType(str, Enum):
    """Platform type"""
    TWITTER = "twitter"
    REDDIT = "reddit"


@dataclass
class SimulationState:
    """Simulation status"""
    simulation_id: str
    project_id: str
    graph_id: str
    
    # which platforms are enabled
    enable_twitter: bool = True
    enable_reddit: bool = True
    
    # status
    status: SimulationStatus = SimulationStatus.CREATED
    
    # preparation data
    entities_count: int = 0
    profiles_count: int = 0
    entity_types: List[str] = field(default_factory=list)
    
    # configuration generation info
    profiles_generated: bool = False
    config_generated: bool = False
    config_reasoning: str = ""
    
    # runtime data
    current_round: int = 0
    twitter_status: str = "not_started"
    reddit_status: str = "not_started"
    
    # timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # error info
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Full state dict (internal use)"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "enable_twitter": self.enable_twitter,
            "enable_reddit": self.enable_reddit,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "profiles_generated": self.profiles_generated,
            "config_generated": self.config_generated,
            "config_reasoning": self.config_reasoning,
            "current_round": self.current_round,
            "twitter_status": self.twitter_status,
            "reddit_status": self.reddit_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }
    
    def get_default_platform(self) -> str:
        """Return the default platform based on which platforms are enabled"""
        if self.enable_twitter and self.enable_reddit:
            return "reddit"  # keep the original default when both are enabled
        elif self.enable_twitter:
            return "twitter"
        else:
            return "reddit"

    def to_simple_dict(self) -> Dict[str, Any]:
        """Simplified state dict (returned by the API)"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "profiles_generated": self.profiles_generated,
            "config_generated": self.config_generated,
            "error": self.error,
        }


class SimulationManager:
    """
    Simulation manager
    
    Core features:
    1. Read entities from the Zep graph and filter them
    2. Generate OASIS agent profiles
    3. Use the LLM to generate simulation configuration parameters
    4. Prepare every file the preset scripts need
    """
    
    # simulation data folder
    SIMULATION_DATA_DIR = Config.OASIS_SIMULATION_DATA_DIR     # per instance (MIROFISH_UPLOAD_DIR)
    
    def __init__(self):
        # make sure the folder exists
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)
        
        # in-memory cache of simulation states
        self._simulations: Dict[str, SimulationState] = {}
    
    def _get_simulation_dir(self, simulation_id: str) -> str:
        """Get the simulation data folder"""
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir
    
    def _save_simulation_state(self, state: SimulationState):
        """Save the simulation state to a file"""
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        state.updated_at = datetime.now().isoformat()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        
        self._simulations[state.simulation_id] = state
    
    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """Load the simulation state from a file"""
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]
        
        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        if not os.path.exists(state_file):
            return None
        
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=data.get("graph_id", ""),
            enable_twitter=data.get("enable_twitter", True),
            enable_reddit=data.get("enable_reddit", True),
            status=SimulationStatus(data.get("status", "created")),
            entities_count=data.get("entities_count", 0),
            profiles_count=data.get("profiles_count", 0),
            entity_types=data.get("entity_types", []),
            profiles_generated=data.get("profiles_generated", False),
            config_generated=data.get("config_generated", False),
            config_reasoning=data.get("config_reasoning", ""),
            current_round=data.get("current_round", 0),
            twitter_status=data.get("twitter_status", "not_started"),
            reddit_status=data.get("reddit_status", "not_started"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
        )
        
        self._simulations[simulation_id] = state
        return state
    
    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> SimulationState:
        """
        Create a new simulation
        
        Args:
            project_id: project ID
            graph_id: Zep graph ID
            enable_twitter: whether to run the Twitter simulation
            enable_reddit: whether to run the Reddit simulation
            
        Returns:
            SimulationState
        """
        import uuid
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.CREATED,
        )
        
        self._save_simulation_state(state)
        logger.info(f"Created simulation: {simulation_id}, project={project_id}, graph={graph_id}")
        
        return state
    
    def prepare_simulation(
        self,
        simulation_id: str,
        simulation_requirement: str,
        document_text: str,
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        progress_callback: Optional[callable] = None,
        parallel_profile_count: int = 3,
        persona_spec: Optional[Dict[str, Any]] = None,
        resume_only: bool = False
    ) -> SimulationState:
        """
        Prepare the simulation environment (fully automatic)
        
        Steps:
        1. Read and filter entities from the Zep graph
        2. Generate an OASIS agent profile for each entity (optional LLM enrichment, can run in parallel)
        3. Use the LLM to generate simulation parameters (timing, activity, posting frequency and so on)
        4. Save the configuration and profile files
        5. Copy the preset scripts to the simulation folder
        
        Args:
            simulation_id: simulation ID
            simulation_requirement: what the simulation should cover (used by the LLM to build the configuration)
            document_text: original document text (gives the LLM background)
            defined_entity_types: predefined entity types (optional)
            use_llm_for_profiles: whether to use the LLM for detailed personas
            progress_callback: progress callback (stage, progress, message)
            parallel_profile_count: number of personas to generate in parallel, default 3
            
        Returns:
            SimulationState
        """
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"模拟不存在: {simulation_id}")
        sim_dir = self._get_simulation_dir(simulation_id)
        if state.profiles_generated and not state.config_generated:
            resumed = self._resume_profile_preparation(state, sim_dir, simulation_requirement, document_text,
                                                       persona_spec, progress_callback)
            if resumed:
                return resumed
        if resume_only:
            raise ValueError("resume-only preparation requires a complete saved profile set and an unfinished config")
        
        try:
            state.status = SimulationStatus.PREPARING
            state.error = None
            state.profiles_generated = False
            state.config_generated = False
            state.config_reasoning = ""
            self._save_simulation_state(state)
            
            sim_dir = self._get_simulation_dir(simulation_id)
            
            # ========== Stage 1: read and filter entities ==========
            if progress_callback:
                progress_callback("reading", 0, t('progress.connectingZepGraph'))
            
            reader = ZepEntityReader()
            
            if progress_callback:
                progress_callback("reading", 30, t('progress.readingNodeData'))
            
            filtered = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True
            )
            
            state.entities_count = filtered.filtered_count
            state.entity_types = list(filtered.entity_types)
            
            if progress_callback:
                progress_callback(
                    "reading", 100,
                    t('progress.readingComplete', count=filtered.filtered_count),
                    current=filtered.filtered_count,
                    total=filtered.filtered_count
                )
            
            # ========== Claude edition: synthetic personas and communities ==========
            spec = persona_planner.PersonaSpec.from_dict(persona_spec) if persona_spec else None
            if spec is not None:
                filtered = self._apply_persona_spec(
                    spec, filtered, simulation_requirement, document_text, sim_dir,
                    parallel_profile_count, progress_callback, project_id=state.project_id)
                state.entities_count = filtered.filtered_count
                state.entity_types = list(filtered.entity_types)
                self._save_simulation_state(state)

            if filtered.filtered_count == 0:
                state.status = SimulationStatus.FAILED
                state.error = "没有找到符合条件的实体，请检查图谱是否正确构建"
                self._save_simulation_state(state)
                raise ValueError(state.error)
            
            # ========== Stage 2: generate agent profiles ==========
            total_entities = len(filtered.entities)
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 0,
                    t('progress.startGenerating'),
                    current=0,
                    total=total_entities
                )
            
            # pass graph_id to turn on Zep retrieval for richer context
            generator = OasisProfileGenerator(graph_id=state.graph_id)
            
            def profile_progress(current, total, msg):
                if progress_callback:
                    progress_callback(
                        "generating_profiles", 
                        int(current / total * 100), 
                        msg,
                        current=current,
                        total=total,
                        item_name=msg
                    )
            
            # path for saving as we go (Reddit JSON format preferred)
            realtime_output_path = None
            realtime_platform = "reddit"
            if state.enable_reddit:
                realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                realtime_platform = "reddit"
            elif state.enable_twitter:
                realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                realtime_platform = "twitter"
            
            profiles = generator.generate_profiles_from_entities(
                entities=filtered.entities,
                use_llm=use_llm_for_profiles,
                progress_callback=profile_progress,
                graph_id=state.graph_id,  # graph_id for Zep retrieval
                parallel_count=parallel_profile_count,  # how many to generate in parallel
                realtime_output_path=realtime_output_path,  # save-as-we-go path
                output_platform=realtime_platform  # output format
            )
            
            state.profiles_count = len(profiles)
            state.profiles_generated = len(profiles) > 0
            self._save_simulation_state(state)
            
            # save the profile files (note: Twitter uses CSV, Reddit uses JSON)
            # Reddit was already saved during generation; save again here to be sure it is complete
            if progress_callback:
                progress_callback(
                    "generating_profiles", 95,
                    t('progress.savingProfiles'),
                    current=total_entities,
                    total=total_entities
                )
            
            if state.enable_reddit:
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                    platform="reddit"
                )
            
            if state.enable_twitter:
                # Twitter uses CSV: OASIS requires it
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                    platform="twitter"
                )
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 100,
                    t('progress.profilesComplete', count=len(profiles)),
                    current=len(profiles),
                    total=len(profiles)
                )
            
            # ========== Stage 3: LLM-generated simulation configuration ==========
            if progress_callback:
                progress_callback(
                    "generating_config", 0,
                    t('progress.analyzingRequirements'),
                    current=0,
                    total=3
                )
            
            config_generator = SimulationConfigGenerator()
            
            if progress_callback:
                progress_callback(
                    "generating_config", 30,
                    t('progress.callingLLMConfig'),
                    current=1,
                    total=3
                )
            
            sim_params = config_generator.generate_config(
                simulation_id=simulation_id,
                project_id=state.project_id,
                graph_id=state.graph_id,
                simulation_requirement=simulation_requirement,
                document_text=document_text,
                entities=filtered.entities,
                enable_twitter=state.enable_twitter,
                enable_reddit=state.enable_reddit
            )
            
            if progress_callback:
                progress_callback(
                    "generating_config", 70,
                    t('progress.savingConfigFiles'),
                    current=2,
                    total=3
                )
            
            # save the configuration file
            config_path = os.path.join(sim_dir, "simulation_config.json")
            config_json = sim_params.to_json()
            if spec is not None:
                config_dict = json.loads(config_json)
                config_dict["persona_spec"] = spec.to_dict()
                config_dict["persona_index"] = persona_planner.persona_index(filtered.entities)
                if spec.communities:
                    config_dict["community_config"] = persona_planner.build_community_config(
                        filtered.entities, spec)
                config_json = json.dumps(config_dict, ensure_ascii=False, indent=2)
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(config_json)
            
            state.config_generated = True
            state.config_reasoning = sim_params.generation_reasoning
            
            if progress_callback:
                progress_callback(
                    "generating_config", 100,
                    t('progress.configComplete'),
                    current=3,
                    total=3
                )
            
            # note: the run scripts stay in backend/scripts/ and are no longer copied to the simulation folder
            # when a simulation starts, simulation_runner runs them from scripts/
            
            # update the state
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)
            
            logger.info(f"Simulation prepared: {simulation_id}, "
                       f"entities={state.entities_count}, profiles={state.profiles_count}")
            
            return state
            
        except Exception as e:
            logger.error(f"Simulation preparation failed: {simulation_id}, error={str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)
            raise

    def _resume_profile_preparation(self, state: SimulationState, sim_dir: str, requirement: str,
                                    document_text: str, persona_spec: Optional[Dict[str, Any]],
                                    progress_callback=None) -> Optional[SimulationState]:
        """Finish config generation from a complete persisted profile set, with no profile LLM calls."""
        profiles_path = os.path.join(sim_dir, "reddit_profiles.json")
        plan_path = os.path.join(sim_dir, "persona_plan.json")
        if not (os.path.isfile(profiles_path) and os.path.isfile(plan_path)):
            return None
        try:
            with open(profiles_path, encoding="utf-8") as f:
                rows = json.load(f)
            with open(plan_path, encoding="utf-8") as f:
                plan = json.load(f)
            kept = plan.get("kept_graph_entities") or []
            generated = plan.get("personas") or []
            expected = len(kept) + len(generated)
            if expected != state.profiles_count or len(rows) != expected or \
                    sorted(r.get("user_id") for r in rows) != list(range(expected)):
                logger.warning("saved profiles are incomplete or out of sequence; normal preparation required")
                return None
            rows_by_id = {r["user_id"]: r for r in rows}
            entities = []
            for idx, name in enumerate(kept):
                r = rows_by_id[idx]
                entities.append(EntityNode(uuid=f"resume-graph-{idx}", name=name, labels=["Entity"],
                                           summary=r.get("persona") or "", attributes={}))
            for offset, raw in enumerate(generated, len(kept)):
                r = rows_by_id[offset]
                attrs = {k: v for k, v in raw.items() if k not in ("name", "labels")}
                attrs[persona_planner.SYNTHETIC_PROFILE_KEY] = {k: r.get(k) for k in
                    ("age", "gender", "country", "profession") if r.get(k) is not None}
                entities.append(EntityNode(uuid=f"resume-persona-{offset}", name=raw["name"],
                                           labels=raw.get("labels") or ["Persona"], summary=r.get("persona") or "",
                                           attributes=attrs))
            saved_spec = persona_spec if persona_spec is not None else plan.get("spec")
            spec = persona_planner.PersonaSpec.from_dict(saved_spec) if saved_spec else None
            if progress_callback:
                progress_callback("generating_profiles", 100, f"Reused {expected} saved profiles",
                                  current=expected, total=expected)
            if state.enable_twitter and not os.path.isfile(os.path.join(sim_dir, "twitter_profiles.csv")):
                profiles = [OasisAgentProfile(user_id=r["user_id"], user_name=r.get("username") or "",
                        name=r.get("name") or "", bio=r.get("bio") or "", persona=r.get("persona") or "",
                        karma=r.get("karma", 1000), age=r.get("age"), gender=r.get("gender"),
                        country=r.get("country"), profession=r.get("profession"),
                        interested_topics=r.get("interested_topics") or []) for r in rows]
                OasisProfileGenerator().save_profiles(profiles, os.path.join(sim_dir, "twitter_profiles.csv"), "twitter")
            if progress_callback:
                progress_callback("generating_config", 30, "Generating missing simulation config", current=1, total=3)
            params = SimulationConfigGenerator().generate_config(
                simulation_id=state.simulation_id, project_id=state.project_id, graph_id=state.graph_id,
                simulation_requirement=requirement, document_text=document_text, entities=entities,
                enable_twitter=state.enable_twitter, enable_reddit=state.enable_reddit)
            config = json.loads(params.to_json())
            if spec:
                config["persona_spec"] = spec.to_dict()
                config["persona_index"] = persona_planner.persona_index(entities)
                if spec.communities:
                    config["community_config"] = persona_planner.build_community_config(entities, spec)
            with open(os.path.join(sim_dir, "simulation_config.json"), "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            state.config_generated = True
            state.config_reasoning = params.generation_reasoning
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)
            if progress_callback:
                progress_callback("generating_config", 100, "Preparation resumed", current=3, total=3)
            return state
        except (OSError, ValueError, TypeError, KeyError) as e:
            logger.warning(f"cannot resume saved profiles: {e}")
            return None
    
    def _apply_persona_spec(self, spec, filtered: FilteredEntities, requirement: str, document_text: str,
                            sim_dir: str, parallel: int, progress_callback=None, project_id: str = None) -> FilteredEntities:
        """Generate synthetic personas (and community accounts) and merge them with real graph actors.

        Agent ids are list positions, so the order here (kept graph entities, then personas, then
        community accounts) is the order used for profiles, config and the follow graph."""

        def persona_progress(done, total, label):
            if progress_callback:
                progress_callback("generating_profiles", int(done / max(total, 1) * 40),
                                  f"Personas {done}/{total}: {label}", current=done, total=total,
                                  item_name=label)

        # the configured pool: with several providers (LLM_POOL) each writes an equal share of the people
        client = Config.get_model_pool()
        context = (document_text or "")[:12000]
        try:                                                   # product profile first, so segments and interviews know the product
            from ..models.project import ProjectManager
            from . import product_profile as pp
            prof = pp.load(ProjectManager._get_project_dir(project_id)) if project_id else None
            if prof:
                context = (pp.render_text(prof) + "\n\n" + context)[:14000]
        except Exception:  # noqa: BLE001 - the profile is optional
            prof = None
        voices = None
        try:
            from ..models.project import ProjectManager
            vpath = os.path.join(ProjectManager._get_project_dir(project_id), "voices.json") if project_id else ""
            if vpath and os.path.exists(vpath):
                with open(vpath, encoding="utf-8") as f:
                    voices = json.load(f)
        except Exception:  # noqa: BLE001 - optional
            voices = None
        personas = persona_planner.generate_personas(
            client, Config.LLM_MODEL_NAME, spec, requirement, context, product=prof, voices=voices,
            progress=persona_progress, parallel=max(1, min(parallel, 16)))
        kept = persona_planner.select_graph_entities(
            filtered.entities, spec, persona_planner.spec_countries(spec))
        dropped = [e.name for e in filtered.entities if e not in kept]
        entities = kept + personas
        with open(os.path.join(sim_dir, "persona_plan.json"), "w", encoding="utf-8") as f:
            json.dump({"spec": spec.to_dict(), "kept_graph_entities": [e.name for e in kept],
                       "dropped_graph_entities": dropped,
                       "personas": [{"name": e.name, "labels": e.labels,
                                     **{k: v for k, v in e.attributes.items()
                                        if k != persona_planner.SYNTHETIC_PROFILE_KEY}} for e in personas]},
                      f, ensure_ascii=False, indent=2)
        logger.info(f"persona spec: kept {len(kept)} graph entities, dropped {len(dropped)}, "
                    f"added {len(personas)} synthetic agents")
        types = {e.get_entity_type() for e in entities if e.get_entity_type()}
        return FilteredEntities(entities=entities, entity_types=types,
                                total_count=filtered.total_count, filtered_count=len(entities))

    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """Get a simulation's state"""
        return self._load_simulation_state(simulation_id)
    
    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """List all simulations"""
        simulations = []
        
        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                # skip hidden files (such as .DS_Store) and anything that is not a folder
                sim_path = os.path.join(self.SIMULATION_DATA_DIR, sim_id)
                if sim_id.startswith('.') or not os.path.isdir(sim_path):
                    continue
                
                state = self._load_simulation_state(sim_id)
                if state:
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)
        
        return simulations
    
    def get_profiles(self, simulation_id: str, platform: str = None) -> List[Dict[str, Any]]:
        """Get a simulation's agent profiles"""
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"模拟不存在: {simulation_id}")

        if platform is None:
            platform = state.get_default_platform()

        if platform not in {"twitter", "reddit"}:
            raise ValueError(f"不支持的平台: {platform}")

        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(
            sim_dir,
            "twitter_profiles.csv" if platform == "twitter" else "reddit_profiles.json",
        )
        
        if not os.path.exists(profile_path):
            return []

        if platform == "twitter":
            import csv

            with open(profile_path, 'r', encoding='utf-8', newline='') as f:
                return list(csv.DictReader(f))

        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """Get the simulation configuration"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """Get the run instructions"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        return {
            "simulation_dir": sim_dir,
            "scripts_dir": scripts_dir,
            "config_file": config_path,
            "commands": {
                "twitter": f"python {scripts_dir}/run_twitter_simulation.py --config {config_path}",
                "reddit": f"python {scripts_dir}/run_reddit_simulation.py --config {config_path}",
                "parallel": f"python {scripts_dir}/run_parallel_simulation.py --config {config_path}",
            },
            "instructions": (
                f"1. 激活conda环境: conda activate MiroFish\n"
                f"2. 运行模拟 (脚本位于 {scripts_dir}):\n"
                f"   - 单独运行Twitter: python {scripts_dir}/run_twitter_simulation.py --config {config_path}\n"
                f"   - 单独运行Reddit: python {scripts_dir}/run_reddit_simulation.py --config {config_path}\n"
                f"   - 并行运行双平台: python {scripts_dir}/run_parallel_simulation.py --config {config_path}"
            )
        }
