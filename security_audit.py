#!/usr/bin/env python3
"""
Security Audit Script
Performs a comprehensive security audit of the Real Freelance Jobs bot
to ensure all security measures are properly implemented.
"""

import os
import re
import asyncio
from pathlib import Path
from typing import Dict, List, Tuple, Any
from datetime import datetime

class SecurityAuditor:
    """Performs security audits on the bot application."""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "total_checks": 0,
            "passed_checks": 0,
            "failed_checks": 0,
            "warnings": [],
            "errors": [],
            "findings": []
        }
    
    def audit_file_structure(self) -> bool:
        """Audit the file structure for security best practices."""
        print("🔍 Auditing file structure...")
        
        # Check for sensitive files
        sensitive_files = [
            ".env",
            ".env.local",
            ".env.production",
            "config.py",
            "secrets.py"
        ]
        
        security_checks = [
            ("no_hardcoded_secrets", self._check_hardcoded_secrets),
            ("proper_file_permissions", self._check_file_permissions),
            ("secure_config_files", self._check_config_files),
            ("backup_files_removed", self._check_backup_files),
        ]
        
        for check_name, check_func in security_checks:
            self.results["total_checks"] += 1
            try:
                result = check_func()
                if result:
                    self.results["passed_checks"] += 1
                    print(f"  ✅ {check_name}")
                else:
                    self.results["failed_checks"] += 1
                    print(f"  ❌ {check_name}")
            except Exception as e:
                self.results["failed_checks"] += 1
                print(f"  ❌ {check_name} - Error: {e}")
        
        return self.results["failed_checks"] == 0
    
    def _check_hardcoded_secrets(self) -> bool:
        """Check for hardcoded secrets in code."""
        sensitive_patterns = [
            r'TELEGRAM_BOT_TOKEN\s*=\s*[\'"][^\'"]{35,}[\'"]',
            r'API_KEY\s*=\s*[\'"][^\'"]{20,}[\'"]',
            r'SECRET\s*=\s*[\'"][^\'"]{10,}[\'"]',
            r'PASSWORD\s*=\s*[\'"][^\'"]{6,}[\'"]'
        ]
        
        python_files = list(self.project_root.rglob("*.py"))
        found_secrets = False
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                for pattern in sensitive_patterns:
                    if re.search(pattern, content):
                        print(f"    🚨 Found potential secret in {file_path}")
                        found_secrets = True
                        
            except Exception as e:
                print(f"    ⚠️ Could not read {file_path}: {e}")
        
        return not found_secrets
    
    def _check_file_permissions(self) -> bool:
        """Check for secure file permissions (simplified check)."""
        # This is a simplified check - in production, you'd check actual file permissions
        # On Windows, we'll just check that the files exist and aren't obviously compromised
        sensitive_files = [".env", "config.py"]
        
        for file_name in sensitive_files:
            file_path = self.project_root / file_name
            if file_path.exists():
                # On Windows, we can't check Unix-style permissions easily
                # Instead, we'll just verify the file exists and can be read
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()
                    
                    # Check for obvious permission issues in content
                    if "your_" not in content and file_name == ".env":
                        print(f"    ⚠️ {file_name} may contain real secrets")
                        return False
                        
                except Exception as e:
                    print(f"    ⚠️ Could not read {file_name}: {e}")
                    return False
        
        return True
    
    def _check_config_files(self) -> bool:
        """Check configuration files for security."""
        env_files = [".env", ".env.example"]
        
        for env_file in env_files:
            file_path = self.project_root / env_file
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()
                    
                    # Check for real tokens in example files
                    if "your_" not in content and env_file == ".env.example":
                        print(f"    ⚠️ {env_file} may contain real secrets")
                        return False
                        
                except Exception as e:
                    print(f"    ⚠️ Could not read {env_file}: {e}")
                    return False
        
        return True
    
    def _check_backup_files(self) -> bool:
        """Check for backup files that might contain sensitive information."""
        backup_patterns = ["*.bak", "*.backup", "*.old", "*~", "*.swp"]
        
        for pattern in backup_patterns:
            backup_files = list(self.project_root.rglob(pattern))
            if backup_files:
                print(f"    ⚠️ Found backup files: {backup_files}")
                return False
        
        return True
    
    def audit_code_security(self) -> bool:
        """Audit code for security vulnerabilities."""
        print("\n🔍 Auditing code security...")
        
        security_checks = [
            ("sql_injection_protection", self._check_sql_injection),
            ("ssrf_protection", self._check_ssrf_protection),
            ("input_validation", self._check_input_validation),
            ("error_handling", self._check_error_handling),
            ("rate_limiting", self._check_rate_limiting),
            ("authentication", self._check_authentication),
            ("admin_security", self._check_admin_security),
            ("owner_protection", self._check_owner_protection),
        ]
        
        for check_name, check_func in security_checks:
            self.results["total_checks"] += 1
            try:
                result = check_func()
                if result:
                    self.results["passed_checks"] += 1
                    print(f"  ✅ {check_name}")
                else:
                    self.results["failed_checks"] += 1
                    print(f"  ❌ {check_name}")
            except Exception as e:
                self.results["failed_checks"] += 1
                print(f"  ❌ {check_name} - Error: {e}")
        
        return self.results["failed_checks"] == 0
    
    def _check_sql_injection(self) -> bool:
        """Check for SQL injection protection."""
        python_files = list(self.project_root.rglob("*.py"))
        
        for file_path in python_files:
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                # Check for unsafe SQL patterns
                unsafe_patterns = [
                    r"execute\s*\(\s*f[\"'].*\{.*\}.*[\"']\s*,",
                    r"cursor\.execute\s*\([^)]+\s+%[^)]+)",
                    r"executemany\s*\("
                ]
                
                for pattern in unsafe_patterns:
                    if re.search(pattern, content):
                        print(f"    🚨 Potential SQL injection in {file_path}")
                        return False
                        
            except Exception:
                pass
        
        return True
    
    def _check_ssrf_protection(self) -> bool:
        """Check for SSRF protection."""
        website_checker = self.project_root / "services" / "website_checker.py"
        
        if not website_checker.exists():
            print("    ⚠️ website_checker.py not found")
            return False
        
        try:
            with open(website_checker, 'r') as f:
                content = f.read()
            
            # Check for SSRF protection - look for validate_url import and usage
            protection_indicators = [
                "from utils.security import validate_url",
                "validate_url(",
                "Blocked localhost",
                "Blocked private IP address",
                "Blocked protocol"
            ]
            
            has_protection = any(indicator in content for indicator in protection_indicators)
            
            if not has_protection:
                print("    ⚠️ No SSRF protection found in website_checker.py")
                return False
                
        except Exception as e:
            print(f"    ⚠️ Could not read website_checker.py: {e}")
            return False
        
        return True
    
    def _check_input_validation(self) -> bool:
        """Check for input validation."""
        security_module = self.project_root / "utils" / "security.py"
        
        if not security_module.exists():
            print("    ⚠️ security.py not found")
            return False
        
        try:
            with open(security_module, 'r') as f:
                content = f.read()
            
            # Check for validation functions
            validation_functions = [
                "validate_user_id",
                "validate_chat_id",
                "validate_job_id",
                "validate_url",
                "validate_email",
                "sanitize_input"
            ]
            
            missing_functions = []
            for func in validation_functions:
                if f"def {func}" not in content:
                    missing_functions.append(func)
            
            if missing_functions:
                print(f"    ⚠️ Missing validation functions: {missing_functions}")
                return False
                
        except Exception as e:
            print(f"    ⚠️ Could not read security.py: {e}")
            return False
        
        return True
    
    def _check_error_handling(self) -> bool:
        """Check for proper error handling."""
        error_handler = self.project_root / "utils" / "error_handler.py"
        
        if not error_handler.exists():
            print("    ⚠️ error_handler.py not found")
            return False
        
        try:
            with open(error_handler, 'r') as f:
                content = f.read()
            
            # Check for error handling patterns
            error_patterns = [
                "handle_error",
                "create_user_safe_error_message",
                "sanitize_error_message",
                "SecurityError"
            ]
            
            missing_patterns = []
            for pattern in error_patterns:
                if pattern not in content:
                    missing_patterns.append(pattern)
            
            if missing_patterns:
                print(f"    ⚠️ Missing error handling patterns: {missing_patterns}")
                return False
                
        except Exception as e:
            print(f"    ⚠️ Could not read error_handler.py: {e}")
            return False
        
        return True
    
    def _check_rate_limiting(self) -> bool:
        """Check for rate limiting implementation."""
        rate_limiter = self.project_root / "utils" / "rate_limiter.py"
        
        if not rate_limiter.exists():
            print("    ⚠️ rate_limiter.py not found")
            return False
        
        try:
            with open(rate_limiter, 'r') as f:
                content = f.read()
            
            # Check for rate limiting patterns
            rate_patterns = [
                "RateLimiter",
                "SecurityRateLimiter",
                "RateLimitManager",
                "is_allowed",
                "check_limit"
            ]
            
            missing_patterns = []
            for pattern in rate_patterns:
                if pattern not in content:
                    missing_patterns.append(pattern)
            
            if missing_patterns:
                print(f"    ⚠️ Missing rate limiting patterns: {missing_patterns}")
                return False
                
        except Exception as e:
            print(f"    ⚠️ Could not read rate_limiter.py: {e}")
            return False
        
        return True
    
    def _check_authentication(self) -> bool:
        """Check for authentication implementation."""
        config_module = self.project_root / "config.py"
        
        if not config_module.exists():
            print("    ⚠️ config.py not found")
            return False
        
        try:
            with open(config_module, 'r') as f:
                content = f.read()
            
            # Check for authentication patterns
            auth_patterns = [
                "OWNER_ID",
                "ADMIN_IDS",
                "is_owner",
                "is_admin"
            ]
            
            missing_patterns = []
            for pattern in auth_patterns:
                if pattern not in content:
                    missing_patterns.append(pattern)
            
            if missing_patterns:
                print(f"    ⚠️ Missing authentication patterns: {missing_patterns}")
                return False
                
        except Exception as e:
            print(f"    ⚠️ Could not read config.py: {e}")
            return False
        
        return True
    
    def _check_admin_security(self) -> bool:
        """Check for admin security implementation."""
        admin_handlers = self.project_root / "handlers" / "admin.py"
        
        if not admin_handlers.exists():
            print("    ⚠️ admin.py not found")
            return False
        
        try:
            with open(admin_handlers, 'r') as f:
                content = f.read()
            
            # Check for admin security patterns
            admin_patterns = [
                "is_authorized_admin",
                "require_admin",
                "validate_admin_callback"
            ]
            
            # Check for either decorator style
            decorator_patterns = [
                "@require_admin_handler",
                "@require_admin"
            ]
            
            missing_patterns = []
            for pattern in admin_patterns:
                if pattern not in content:
                    missing_patterns.append(pattern)
            
            # Check if any decorator pattern exists
            has_decorator = any(pattern in content for pattern in decorator_patterns)
            
            if missing_patterns or not has_decorator:
                all_missing = missing_patterns.copy()
                if not has_decorator:
                    all_missing.append("admin decorator (@require_admin_handler or @require_admin)")
                print(f"    ⚠️ Missing admin security patterns: {all_missing}")
                return False
                
        except Exception as e:
            print(f"    ⚠️ Could not read admin.py: {e}")
            return False
        
        return True
    
    def _check_owner_protection(self) -> bool:
        """Check for owner protection implementation."""
        crud_module = self.project_root / "database" / "crud.py"
        
        if not crud_module.exists():
            print("    ⚠️ crud.py not found")
            return False
        
        try:
            with open(crud_module, 'r') as f:
                content = f.read()
            
            # Check for owner protection patterns
            owner_patterns = [
                "settings.is_owner",
                "AuthorizationError",
                "cannot be banned",
                "cannot be restricted"
            ]
            
            has_protection = any(pattern in content.lower() for pattern in owner_patterns)
            
            if not has_protection:
                print("    ⚠️ No owner protection found in crud.py")
                return False
                
        except Exception as e:
            print(f"    ⚠️ Could not read crud.py: {e}")
            return False
        
        return True
    
    def audit_dependencies(self) -> bool:
        """Audit dependencies for security."""
        print("\n🔍 Auditing dependencies...")
        
        # Check for requirements.txt or pyproject.toml
        requirements_files = ["requirements.txt", "pyproject.toml"]
        
        for req_file in requirements_files:
            file_path = self.project_root / req_file
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()
                    
                    # Check for known vulnerable packages (simplified)
                    vulnerable_packages = ["requests<2.25.0", "urllib3<1.26.0"]
                    
                    for vuln_package in vulnerable_packages:
                        if vuln_package in content:
                            print(f"    ⚠️ Potentially vulnerable package: {vuln_package}")
                            return False
                            
                except Exception as e:
                    print(f"    ⚠️ Could not read {req_file}: {e}")
                    return False
        
        return True
    
    def generate_report(self) -> str:
        """Generate a security audit report."""
        report = []
        report.append("=" * 60)
        report.append("🔒 SECURITY AUDIT REPORT")
        report.append("=" * 60)
        report.append(f"Audit Date: {self.results['timestamp']}")
        report.append("")
        
        # Summary
        report.append("📊 SUMMARY")
        report.append("-" * 30)
        report.append(f"Total Checks: {self.results['total_checks']}")
        report.append(f"Passed: {self.results['passed_checks']}")
        report.append(f"Failed: {self.results['failed_checks']}")
        report.append(f"Success Rate: {self.results['passed_checks'] / self.results['total_checks'] * 100:.1f}%")
        report.append("")
        
        # Recommendations
        report.append("📋 RECOMMENDATIONS")
        report.append("-" * 30)
        
        if self.results["failed_checks"] > 0:
            report.append("❌ CRITICAL ISSUES FOUND:")
            report.append("  - Fix all failed security checks before deployment")
            report.append("  - Review failed checks in detail above")
            report.append("")
        
        if self.results["warnings"]:
            report.append("⚠️ WARNINGS:")
            for warning in self.results["warnings"]:
                report.append(f"  - {warning}")
            report.append("")
        
        # Best practices
        report.append("💡 SECURITY BEST PRACTICES:")
        report.append("  - Regularly update dependencies")
        report.append("  - Implement logging and monitoring")
        report.append("  - Use environment variables for secrets")
        report.append("  - Implement proper access controls")
        report.append("  - Regular security audits")
        report.append("")
        
        report.append("=" * 60)
        
        return "\n".join(report)
    
    def run_audit(self) -> bool:
        """Run the complete security audit."""
        print("🚀 Starting Security Audit...")
        
        # Run all audits
        self.audit_file_structure()
        self.audit_code_security()
        self.audit_dependencies()
        
        # Generate and display report
        report = self.generate_report()
        print("\n" + report)
        
        # Return True if audit passed
        return self.results["failed_checks"] == 0


def main():
    """Main entry point."""
    project_root = str(Path(__file__).parent)
    auditor = SecurityAuditor(project_root)
    
    success = auditor.run_audit()
    
    if success:
        print("🎉 SECURITY AUDIT PASSED!")
        return 0
    else:
        print("❌ SECURITY AUDIT FAILED!")
        return 1


if __name__ == "__main__":
    exit(main())