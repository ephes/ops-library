#!/usr/bin/env python3
"""
FastDeploy-self service runner
Handles self-deployment with API-based progress reporting
"""
import json
import subprocess
import sys
import os
import time
import tempfile
import argparse
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import httpx
except ImportError:
    httpx = None


class DeploymentReporter:
    """Handle deployment progress reporting via API or stdout."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.client = None
        self.api_enabled = False
        
        if self.config and httpx:
            access_token = self.config.get("access_token")
            self.steps_url = self.config.get("steps_url")
            
            if access_token and self.steps_url:
                self.api_enabled = True
                self.headers = {"authorization": f"Bearer {access_token}"}
                self.client = httpx.Client(headers=self.headers, timeout=10.0)
    
    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load deployment configuration from secure file."""
        if not config_path:
            config_path = os.environ.get("DEPLOY_CONFIG_FILE")
        
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}
    
    def emit_step(self, name: str, state: str, message: str = ""):
        """Report deployment step progress."""
        step_data = {
            "name": name,
            "state": state,
            "message": message[:4096] if message else ""
        }
        
        # Always emit to stdout for compatibility
        print(json.dumps(step_data), flush=True)
        
        # Also send to API if available
        if self.api_enabled and self.client:
            try:
                response = self.client.post(self.steps_url, json=step_data)
                response.raise_for_status()
            except Exception as e:
                # Log API errors but don't fail the deployment
                print(f"Warning: Failed to report step via API: {e}", file=sys.stderr)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            self.client.close()


def parse_ansible_output(output: str) -> str:
    """Extract meaningful error message from Ansible output."""
    if "FAILED!" in output:
        lines = output.split('\n')
        for i, line in enumerate(lines):
            if "FAILED!" in line:
                # Get context around the failure
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                return ' '.join(lines[start:end])[:500]
    
    # Look for other error patterns
    for pattern in ["ERROR!", "fatal:", "UNREACHABLE!"]:
        if pattern in output:
            for line in output.split('\n'):
                if pattern in line:
                    return line[:500]
    
    return "Deployment failed"


def main():
    """Run the self-deployment playbook."""
    parser = argparse.ArgumentParser(description='FastDeploy self-deployment runner')
    parser.add_argument('--config', help='Path to deployment config file')
    args = parser.parse_args()
    
    # Set secure umask
    os.umask(0o077)
    
    # Initialize reporter
    with DeploymentReporter(args.config) as reporter:
        # Emit prepare step
        reporter.emit_step("prepare", "running", "Preparing FastDeploy self-deployment")
        
        # Prepare environment
        runner_dir = Path(__file__).parent
        env = os.environ.copy()
        env.update({
            'SOPS_AGE_KEY_FILE': '/home/deploy/.config/sops/age/keys.txt',
            'ANSIBLE_CONFIG': str(runner_dir / 'ansible.cfg'),
            'ANSIBLE_HOST_KEY_CHECKING': 'false',  # localhost only
            'ANSIBLE_FORCE_COLOR': 'false',  # Disable color output
        })
        
        # Build ansible command
        cmd = [
            "/usr/bin/ansible-playbook",
            "-i", "localhost,",
            "-c", "local",
            str(runner_dir / 'playbook.yml'),
            "-v"  # Verbose for deployment tracking
        ]
        
        reporter.emit_step("prepare", "success", "Environment prepared")
        
        # Run deployment
        reporter.emit_step("deploy", "running", "Running Ansible playbook for self-deployment")
        
        start_time = time.time()
        
        try:
            # Run ansible-playbook and capture output
            result = subprocess.run(
                cmd,
                cwd=str(runner_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=600
            )
            
            duration = time.time() - start_time
            
            if result.returncode == 0:
                reporter.emit_step("deploy", "success", f"Deployment completed in {duration:.1f}s")
                
                # Log output for debugging
                if result.stdout or result.stderr:
                    debug_output = {
                        "stdout": result.stdout[-10000:],  # Last 10KB
                        "stderr": result.stderr[-10000:],
                        "returncode": 0,
                        "status": "success"
                    }
                    print(json.dumps(debug_output), file=sys.stderr)
                
                return 0
            else:
                # Extract error from ansible output
                error_msg = parse_ansible_output(result.stdout + result.stderr)
                reporter.emit_step("deploy", "failure", error_msg)
                
                # Log full output for debugging
                debug_output = {
                    "stdout": result.stdout[-10000:],
                    "stderr": result.stderr[-10000:],
                    "returncode": result.returncode,
                    "status": "failed",
                    "error": error_msg
                }
                print(json.dumps(debug_output), file=sys.stderr)
                
                return 1
                
        except subprocess.TimeoutExpired:
            reporter.emit_step("deploy", "failure", "Deployment timeout after 10 minutes")
            return 1
        except Exception as e:
            reporter.emit_step("deploy", "failure", f"Unexpected error: {str(e)}")
            return 1


if __name__ == "__main__":
    sys.exit(main())