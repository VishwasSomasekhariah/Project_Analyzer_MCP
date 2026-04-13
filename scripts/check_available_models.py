#!/usr/bin/env python3

import asyncio
import os
from openai import AsyncOpenAI

async def check_available_models():
    """Check what models are currently available through OpenAI API"""
    
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    try:
        print("🔍 Fetching available OpenAI models...")
        models = await client.models.list()
        
        print(f"📊 Found {len(models.data)} total models\n")
        
        # Group models by type
        model_groups = {
            'GPT-4': [],
            'GPT-3.5': [],
            'O-Series (Reasoning)': [],
            'Other': []
        }
        
        for model in models.data:
            model_id = model.id
            if 'gpt-4' in model_id.lower():
                model_groups['GPT-4'].append(model_id)
            elif 'gpt-3.5' in model_id.lower():
                model_groups['GPT-3.5'].append(model_id)
            elif any(x in model_id.lower() for x in ['o1', 'o3', 'o4']):
                model_groups['O-Series (Reasoning)'].append(model_id)
            else:
                model_groups['Other'].append(model_id)
        
        # Print organized results
        for group_name, model_list in model_groups.items():
            if model_list:
                print(f"🧠 **{group_name}** ({len(model_list)} models):")
                for model_id in sorted(model_list):
                    print(f"   • {model_id}")
                print()
        
        # Specifically check for O3 models
        o3_models = [m for m in [model.id for model in models.data] if 'o3' in m.lower()]
        print(f"🔎 **O3 Models Specifically Available**: {len(o3_models)}")
        for model in sorted(o3_models):
            print(f"   ✅ {model}")
        
        if not o3_models:
            print("   ❌ No O3 models found in available models list")
            
        # Check for o3-mini-high specifically
        o3_mini_high_available = any('o3-mini-high' in model.id for model in models.data)
        print(f"\n🎯 **o3-mini-high availability**: {'✅ Available' if o3_mini_high_available else '❌ Not Available'}")
        
    except Exception as e:
        print(f"❌ Error fetching models: {e}")

if __name__ == "__main__":
    asyncio.run(check_available_models())