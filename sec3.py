import gymnasium as gym
from gymnasium.envs.toy_text.frozen_lake import generate_random_map
import numpy as np
from collections import defaultdict
from tqdm import tqdm
import pickle
import torch
from collections import deque
import collections

collections.Callable = collections.abc.Callable

import torch.nn as nn
import torch.optim as optim
import wandb
import random
import os

# os.environ["WANDB_DISABLE_CODE"]="true"
wandb.setup(wandb.Settings(program="Q3.py", program_relpath="Q3.py"))
wandb.login(key="--")


class DQN3Layers(nn.Module):
    def __init__(self, state_size, action_size=2):
        super(DQN3Layers, self).__init__()
        self.network = nn.Sequential(
            nn.Linear(state_size, 32),  # Input layer to first hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # First hidden layer to second hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # Second hidden layer to third hidden layer
            nn.ReLU(),
            nn.Linear(32, action_size)  # Third hidden layer to output layer
        )

    def forward(self, state):
        return self.network(state)


class DQN5Layers(nn.Module):
    def __init__(self, state_size, action_size=2):
        super(DQN5Layers, self).__init__()
        self.network = nn.Sequential(
            nn.Linear(state_size, 32),  # Input layer to first hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # First hidden layer to second hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # Second hidden layer to third hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # Third hidden layer to fourth hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # Fourth hidden layer to fifth hidden layer
            nn.ReLU(),
            nn.Linear(32, action_size)  # Fifth hidden layer to output layer
        )

    def forward(self, state):
        return self.network(state)



# Agent Class
class CAgent:
    def __init__(self, env, model, learning_rate, initial_epsilon, epsilon_decay, final_epsilon, discount_factor):
        self.env = env
        self.model = model
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)

        # if self.model.__name__ == "DQN3Layers":
        #     self.target_model = DQN3Layers(env.observation_space.shape[0], env.action_space.n).to(self.device)
        #     self.target_model.load_state_dict(self.model.state_dict())
        # else:
        #     self.target_model = DQN5Layers(env.observation_space.shape[0], env.action_space.n).to(self.device)
        #     self.target_model.load_state_dict(self.model.state_dict())
        self.target_model =  DQN5Layers(env.observation_space.shape[0], env.action_space.n).to(self.device)
        self.target_model.load_state_dict(self.model.state_dict())
        self.target_model.eval()

        self.optimizer = optim.Adam(self.model.parameters(), lr=learning_rate)
        self.criterion = nn.MSELoss()
        self.replay_memory = deque(maxlen=10000)

        self.epsilon = initial_epsilon
        self.epsilon_decay = epsilon_decay
        self.final_epsilon = final_epsilon
        self.discount_factor = discount_factor

    def sample_action(self, state):
        if np.random.random() < self.epsilon:
            return self.env.action_space.sample()
        state_tensor = torch.FloatTensor(state).to(self.device).unsqueeze(0)
        with torch.no_grad():
            return torch.argmax(self.model(state_tensor)).item()

    def test_action(self, state):
        state_tensor = torch.FloatTensor(state).to(self.device).unsqueeze(0)
        with torch.no_grad():
            return torch.argmax(self.model(state_tensor)).item()

    def decay_epsilon(self):
        self.epsilon = max(self.final_epsilon, self.epsilon * (1 - self.epsilon_decay))

    def store_experience(self, experience):
        self.replay_memory.append(experience)

    def sample_batch(self, batch_size):
        return random.sample(self.replay_memory, batch_size)

    def update_target_model(self):
        self.target_model.load_state_dict(self.model.state_dict())

    def train_on_batch(self, batch_size):
        if len(self.replay_memory) < batch_size:
            return None
        batch = self.sample_batch(batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)

        states = torch.FloatTensor(np.array(states)).to(self.device)
        actions = torch.LongTensor(actions).to(self.device)
        rewards = torch.FloatTensor(rewards).to(self.device)
        next_states = torch.FloatTensor(next_states).to(self.device)
        dones = torch.FloatTensor(dones).to(self.device)

        current_q_values = self.model(states).gather(1, actions.unsqueeze(-1)).squeeze(-1)
        with torch.no_grad():
            max_next_q_values = self.target_model(next_states).max(1)[0]
            target_q_values = rewards + (1 - dones) * self.discount_factor * max_next_q_values

        loss = self.criterion(current_q_values, target_q_values)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        return loss.item()


# train an agent with importance sampling
class prioritized_replay_buffer:
    def __init__(self, max_size, alpha=0.2, beta_start=0.4, beta_increment=0.001):
        """
        A prioritized replay buffer for experience sampling with importance sampling.

        Args:
            max_size: Maximum size of the buffer.
            alpha: How much prioritization is used (0 = uniform sampling, 1 = fully prioritized).
            beta_start: Starting value of beta for importance sampling weights.
            beta_increment: Increment for beta per step to approach unbiased sampling.
        """
        self.exp_buffer = []
        self.error_buffer = []
        self.max_size = max_size
        self.alpha = alpha
        self.beta = beta_start
        self.beta_increment = beta_increment

    def add(self, experience, error):
        """
        Add an experience to the buffer with an associated error.

        Args:
            experience: The experience to store (state, action, reward, next_state, done).
            error: TD error associated with the experience.
        """
        priority = (abs(error) + 1e-6) ** self.alpha
        if len(self.exp_buffer) >= self.max_size:
            self.exp_buffer.pop(0)
            self.error_buffer.pop(0)
        self.exp_buffer.append(experience)
        self.error_buffer.append(priority)

    def sample(self, batch_size):
        """
        Sample a batch of experiences using prioritized probabilities.

        Args:
            batch_size: Number of experiences to sample.

        Returns:
            A tuple of (sampled experiences, indices, importance sampling weights).
        """
        priorities = np.array(self.error_buffer)
        probabilities = priorities / sum(priorities)
        indices = np.random.choice(len(self.exp_buffer), batch_size, p=probabilities)
        samples = [self.exp_buffer[i] for i in indices]

        # Compute importance sampling weights
        total = len(self.exp_buffer)
        weights = (total * probabilities[indices]) ** (-self.beta)
        weights /= weights.max()  # Normalize weights
        self.beta = min(1.0, self.beta + self.beta_increment)  # Increase beta over time

        return samples, indices, weights

    def update_priority(self, indices, errors):
        """
        Update priorities of sampled experiences.

        Args:
            indices: Indices of the sampled experiences.
            errors: TD errors for the corresponding indices.
        """
        for idx, error in zip(indices, errors):
            self.error_buffer[idx] = (abs(error) + 1e-6) ** self.alpha

class CAgentIS:
    def __init__(self, env, model, learning_rate, initial_epsilon, epsilon_decay, final_epsilon, discount_factor, buffer_size=10000):
        self.env = env
        self.model = model
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)

        self.target_model = type(model)(env.observation_space.shape[0], env.action_space.n).to(self.device)
        self.target_model.load_state_dict(self.model.state_dict())
        self.target_model.eval()

        self.optimizer = optim.Adam(self.model.parameters(), lr=learning_rate)
        self.criterion = nn.MSELoss(reduction='none')  # Use reduction='none' for PER
        self.replay_buffer = prioritized_replay_buffer(max_size=buffer_size)

        self.epsilon = initial_epsilon
        self.epsilon_decay = epsilon_decay
        self.final_epsilon = final_epsilon
        self.discount_factor = discount_factor

    def sample_action(self, state):
        if np.random.random() < self.epsilon:
            return self.env.action_space.sample()
        state_tensor = torch.FloatTensor(state).to(self.device).unsqueeze(0)
        with torch.no_grad():
            return torch.argmax(self.model(state_tensor)).item()
        
    def test_action(self, state):
        state_tensor = torch.FloatTensor(state).to(self.device).unsqueeze(0)
        with torch.no_grad():
            return torch.argmax(self.model(state_tensor)).item()

    def decay_epsilon(self):
        self.epsilon = max(self.final_epsilon, self.epsilon * (1 - self.epsilon_decay))

    def store_experience(self, experience, error):
        self.replay_buffer.add(experience, error)

    def train_on_batch(self, batch_size):
        if len(self.replay_buffer.exp_buffer) < batch_size:
            return None
        batch, indices, weights = self.replay_buffer.sample(batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)

        states = torch.FloatTensor(np.array(states)).to(self.device)
        actions = torch.LongTensor(actions).to(self.device)
        rewards = torch.FloatTensor(rewards).to(self.device)
        next_states = torch.FloatTensor(next_states).to(self.device)
        dones = torch.FloatTensor(dones).to(self.device)
        weights = torch.FloatTensor(weights).to(self.device)

        current_q_values = self.model(states).gather(1, actions.unsqueeze(-1)).squeeze(-1)
        with torch.no_grad():
            max_next_q_values = self.target_model(next_states).max(1)[0]
            target_q_values = rewards + (1 - dones) * self.discount_factor * max_next_q_values

        errors = torch.abs(current_q_values - target_q_values)
        loss = (weights * self.criterion(current_q_values, target_q_values)).mean()

        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        self.replay_buffer.update_priority(indices, errors.cpu().detach().numpy())

        return loss.item()


    def update_target_model(self):
        self.target_model.load_state_dict(self.model.state_dict())


env = gym.make('CartPole-v1')


# write a test function to test the agent, this function will be called while training the agent
def test_agent(env, agent, episodes=100):
    rewards = []
    for episode in range(episodes):
        state, _ = env.reset()
        total_reward = 0
        for t in range(500):
            action = agent.test_action(state)
            next_state, reward, done, truncated, _ = env.step(action)
            state = next_state
            total_reward += reward
            if done:
                break
        rewards.append(total_reward)
    return rewards


#Training Function
def train_agent(env, agent, episodes, batch_size, target_update_every):
    rewards = []
    losses = []

    for episode in range(episodes):
        state, _ = env.reset()
        total_reward = 0
        episode_losses = []
        done = False
        truncated = False
        first_time_passed = 8000
        while not (done or truncated):
            action = agent.sample_action(state)
            next_state, reward, done, truncated, _ = env.step(action)
            agent.store_experience((state, action, reward, next_state, done))
            state = next_state
            total_reward += reward
            
            if len(agent.replay_memory) >= batch_size:
                loss = agent.train_on_batch(batch_size)
                if loss is not None:
                    episode_losses.append(loss)
    
                if done:
                    break
                
        agent.decay_epsilon()
        rewards.append(total_reward)
        losses.extend(episode_losses)

        if episode % target_update_every == 0:
            agent.update_target_model()

        if episode % 50 == 0:
            agent.model.eval()
            test_rewards = test_agent(env, agent)
            wandb.log({"test_reward": np.mean(test_rewards)})
            if (np.mean(test_rewards) > 475) and (first_time_passed == 8000):
                first_time_passed = episode
            agent.model.train()


        wandb.log({"Reward": total_reward, "Loss": np.mean(episode_losses)})

        print(f"Episode {episode} - Reward: {total_reward}, Loss: {np.mean(episode_losses):.4f}")

    avg_reward = np.mean(rewards[-100:])
    return first_time_passed


def train_agentIS(env, agent, episodes, batch_size, target_update_every):
    rewards = []
    losses = []
    solved_at = None  # To track when the agent solves the environment
    first_time_passed = 8000

    for episode in range(episodes):
        state, _ = env.reset()
        total_reward = 0
        episode_losses = []

        for t in range(500):
            action = agent.sample_action(state)
            next_state, reward, done, truncated, _ = env.step(action)
            td_error = abs(reward)  # Initial priority for new experiences
            agent.store_experience((state, action, reward, next_state, done), td_error)
            state = next_state
            total_reward += reward

            if len(agent.replay_buffer.exp_buffer) >= batch_size:
                loss = agent.train_on_batch(batch_size)
                if loss is not None:
                    episode_losses.append(loss)

            if done:
                break

        agent.decay_epsilon()
        rewards.append(total_reward)
        losses.extend(episode_losses)

        if episode % target_update_every == 0:
            agent.update_target_model()

        if episode % 50 == 0:
            agent.model.eval()
            test_rewards = test_agent(env, agent)
            wandb.log({"test_reward": np.mean(test_rewards)})
            if (np.mean(test_rewards) > 475) and (first_time_passed == 8000):
                first_time_passed = episode
            agent.model.train()

        wandb.log({"Reward": total_reward, "Loss": np.mean(episode_losses)})

        print(f"Episode {episode} - Reward: {total_reward}, Loss: {np.mean(episode_losses):.4f}")

    return solved_at



# run with importance sampling
hyperparameters = Model=DQN5Layers_LR=0.0001_ED=0.1_DF=0.95_BS=1024

agent = CAgentIS(
    env,
    DQN5Layers(env.observation_space.shape[0], env.action_space.n),
    learning_rate=0.01,
    initial_epsilon=1.0,
    epsilon_decay=0.1,
    final_epsilon=0.01,
    discount_factor=0.95,
)
wandb.init(project="DRL_HW1_Q3", name="Importance Sampling")
train_agentIS(env, agent, 1200, 1024, 2)



# agent = CAgent(
#     env,
#     DQN5Layers(env.observation_space.shape[0], env.action_space.n),
#     learning_rate=0.01,
#     initial_epsilon=1.0,
#     epsilon_decay=0.1,
#     final_epsilon=0.01,
#     discount_factor=0.95,
# )
# wandb.init(project="DRL_HW1_Q3", name="No Importance Sampling")
# train_agent(env, agent, 1200, 1024, 2)

